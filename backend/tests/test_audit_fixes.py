"""Regression tests for the API audit (see `API_AUDIT.md`).

Each class pins one fix that would otherwise rot silently: the store list that
answered 500 to an ordering parameter, the error envelope, the request id, the
public cache validators, the throttles and cursor paging.
"""

from urllib.parse import urlparse

import pytest
from django.urls import reverse
from rest_framework.throttling import SimpleRateThrottle

from core.enums import NotificationType
from notifications import services as notification_services


class TestStoreBrowse:
    def test_ordering_is_not_a_500(self, api_client, store):
        response = api_client.get(reverse("public:store-list"), {"ordering": "name"})

        assert response.status_code == 200, response.data

    def test_is_open_excludes_a_store_without_hours(self, api_client, store):
        response = api_client.get(reverse("public:store-list"), {"is_open": "true"})

        assert response.status_code == 200
        assert response.data["count"] == 0

    def test_q_filters_in_the_database(self, api_client, store, other_store):
        response = api_client.get(reverse("public:store-list"), {"q": "burger"})

        assert [row["slug"] for row in response.data["results"]] == [other_store.slug]

    def test_a_bad_radius_is_a_400_not_a_500(self, api_client, store):
        response = api_client.get(
            reverse("public:store-list"),
            {"lat": "33.51", "lng": "36.29", "radius": "near"},
        )

        assert response.status_code == 400
        assert "radius" in response.data


class TestErrorEnvelope:
    def test_object_level_error_carries_a_code_and_the_request_id(self, api_client):
        response = api_client.get("/api/v1/addresses/")

        assert response.status_code == 401
        assert response.data["code"] == "not_authenticated"
        assert response.data["request_id"] == response["X-Request-ID"]

    def test_field_validation_keeps_drfs_shape(self, api_client):
        response = api_client.post(reverse("auth:register"), {}, format="json")

        assert response.status_code == 400
        assert "email" in response.data
        assert "code" not in response.data

    def test_a_business_rule_answers_its_own_code(self, api_client, store):
        response = api_client.post(
            reverse("public:store-delivery-quote", kwargs={"slug": store.slug}),
            {"lat": "0", "lng": "0"},
            format="json",
        )

        assert response.status_code == 422
        assert response.data["code"] == "business_rule"


class TestRequestID:
    def test_a_caller_supplied_id_is_echoed(self, api_client):
        response = api_client.get("/healthz/", HTTP_X_REQUEST_ID="checkout-42")

        assert response["X-Request-ID"] == "checkout-42"

    def test_an_unsafe_id_is_replaced(self, api_client):
        response = api_client.get("/healthz/", HTTP_X_REQUEST_ID="not a header value")

        assert response["X-Request-ID"] != "not a header value"
        assert len(response["X-Request-ID"]) == 32

    def test_a_minted_id_is_returned(self, api_client):
        response = api_client.get("/healthz/")

        assert len(response["X-Request-ID"]) == 32


class TestPublicCache:
    def test_store_list_is_cacheable(self, api_client, store):
        response = api_client.get(reverse("public:store-list"))

        assert response["Cache-Control"].startswith("public, max-age=60")
        assert response["ETag"].startswith('"')

    def test_a_matching_etag_answers_304(self, api_client, store):
        first = api_client.get(reverse("public:store-list"))
        second = api_client.get(reverse("public:store-list"), HTTP_IF_NONE_MATCH=first["ETag"])

        assert second.status_code == 304
        assert second.content == b""

    def test_a_private_response_is_not_cacheable(self, auth_client):
        response = auth_client.get("/api/v1/carts/")

        assert response.status_code == 200
        assert "Cache-Control" not in response


class TestThrottling:
    pytestmark = pytest.mark.django_db

    def test_login_answers_429_with_retry_after(self, api_client, monkeypatch):
        monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "auth", "2/min")
        payload = {"email": "nobody@example.com", "password": "wrong-password"}

        for _ in range(2):
            api_client.post(reverse("auth:login"), payload, format="json")

        response = api_client.post(reverse("auth:login"), payload, format="json")

        assert response.status_code == 429
        assert 0 < int(response["Retry-After"]) <= 60
        assert response.data["code"] == "throttled"

    def test_a_named_scope_keeps_the_global_budget(self, api_client, monkeypatch):
        monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "anon", "2/min")

        for _ in range(2):
            api_client.get(reverse("public:store-list"))

        assert api_client.get(reverse("public:store-list")).status_code == 429


class TestHistoryPagination:
    pytestmark = pytest.mark.django_db

    def test_notifications_page_with_a_cursor(self, auth_client, customer):
        for index in range(3):
            notification_services.notify(
                customer, type=NotificationType.SYSTEM, title=f"note-{index}"
            )

        first = auth_client.get(reverse("notifications:notification-list"), {"page_size": 2})

        assert first.status_code == 200
        assert "count" not in first.data
        assert [row["title"] for row in first.data["results"]] == ["note-2", "note-1"]
        assert first.data["next"] is not None

        cursor = urlparse(first.data["next"])
        second = auth_client.get(f"{cursor.path}?{cursor.query}")

        assert [row["title"] for row in second.data["results"]] == ["note-0"]
        assert second.data["next"] is None
        assert second.data["previous"] is not None

    def test_the_order_list_is_cursor_paged(self, auth_client, customer, store):
        from tests.test_tenancy import _order

        for suffix in range(3):
            _order(store, customer, suffix=suffix)

        first = auth_client.get(reverse("orders:order-list"), {"page_size": 2})

        assert "count" not in first.data
        assert len(first.data["results"]) == 2
        assert first.data["next"] is not None

        cursor = urlparse(first.data["next"])
        second = auth_client.get(f"{cursor.path}?{cursor.query}")

        assert len(second.data["results"]) == 1
        assert second.data["next"] is None
        assert {row["id"] for row in first.data["results"]} & {
            row["id"] for row in second.data["results"]
        } == set()
