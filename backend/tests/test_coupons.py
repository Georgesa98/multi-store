"""Coupons: store CRUD, platform-wide coupons, validation and tenancy."""

from decimal import Decimal

import pytest
from django.urls import reverse

from catalog import services as catalog_services
from core.enums import CouponType, ProductStatus
from orders.models import Coupon

pytestmark = pytest.mark.django_db


def _payload(**overrides):
    data = {
        "code": "TAKE10",
        "discount_type": CouponType.PERCENT,
        "value": "10.00",
    }
    data.update(overrides)
    return data


class TestDashboardCoupons:
    def test_create_and_list_a_store_coupon(self, dashboard_client, store):
        created = dashboard_client.post(reverse("dashboard:coupon-list"), _payload(), format="json")

        assert created.status_code == 201, created.data
        assert created.data["used_count"] == 0
        assert Coupon.objects.get(code="TAKE10").store == store

        listing = dashboard_client.get(reverse("dashboard:coupon-list"))
        assert listing.data["count"] == 1

    def test_percent_cannot_exceed_one_hundred(self, dashboard_client):
        response = dashboard_client.post(
            reverse("dashboard:coupon-list"),
            _payload(value="150.00"),
            format="json",
        )
        assert response.status_code == 400
        assert "value" in response.data

    def test_a_coupon_must_end_after_it_starts(self, dashboard_client):
        response = dashboard_client.post(
            reverse("dashboard:coupon-list"),
            _payload(
                starts_at="2026-05-02T00:00:00Z",
                ends_at="2026-05-01T00:00:00Z",
            ),
            format="json",
        )
        assert response.status_code == 400
        assert "ends_at" in response.data

    def test_a_code_is_unique_within_the_store(self, dashboard_client):
        assert (
            dashboard_client.post(
                reverse("dashboard:coupon-list"), _payload(), format="json"
            ).status_code
            == 201
        )

        duplicate = dashboard_client.post(
            reverse("dashboard:coupon-list"),
            _payload(code="take10"),
            format="json",
        )

        assert duplicate.status_code == 400
        assert "code" in duplicate.data

    def test_the_same_code_may_be_used_by_another_store(
        self, dashboard_client, other_dashboard_client
    ):
        assert (
            dashboard_client.post(
                reverse("dashboard:coupon-list"), _payload(), format="json"
            ).status_code
            == 201
        )

        response = other_dashboard_client.post(
            reverse("dashboard:coupon-list"), _payload(), format="json"
        )

        assert response.status_code == 201, response.data
        assert Coupon.objects.filter(code="TAKE10").count() == 2

    def test_list_is_store_scoped(self, dashboard_client, other_dashboard_client):
        dashboard_client.post(reverse("dashboard:coupon-list"), _payload(), format="json")
        other_dashboard_client.post(
            reverse("dashboard:coupon-list"),
            _payload(code="OTHER5", discount_type=CouponType.FIXED, value="500.00"),
            format="json",
        )

        mine = dashboard_client.get(reverse("dashboard:coupon-list"))

        assert mine.data["count"] == 1
        assert mine.data["results"][0]["code"] == "TAKE10"

    def test_update_and_deactivate(self, dashboard_client):
        coupon_id = dashboard_client.post(
            reverse("dashboard:coupon-list"), _payload(), format="json"
        ).data["id"]
        detail = reverse("dashboard:coupon-detail", kwargs={"pk": coupon_id})

        updated = dashboard_client.patch(detail, {"value": "15.00"}, format="json")
        assert updated.status_code == 200, updated.data
        assert updated.data["value"] == "15.00"

        deleted = dashboard_client.delete(detail)
        assert deleted.status_code == 204

        coupon = Coupon.objects.get(pk=coupon_id)
        assert coupon.is_active is False
        assert coupon.value == Decimal("15.00")

    def test_cross_tenant_detail_is_404(self, dashboard_client, other_dashboard_client):
        coupon_id = dashboard_client.post(
            reverse("dashboard:coupon-list"), _payload(), format="json"
        ).data["id"]

        response = other_dashboard_client.get(
            reverse("dashboard:coupon-detail", kwargs={"pk": coupon_id})
        )

        assert response.status_code == 404

    def test_staff_cannot_create_but_may_read(self, dashboard_client, staff_client):
        assert staff_client.get(reverse("dashboard:coupon-list")).status_code == 200

        response = staff_client.post(reverse("dashboard:coupon-list"), _payload(), format="json")
        assert response.status_code == 403


class TestPlatformCoupons:
    def test_a_platform_coupon_has_no_store(self, platform_client):
        response = platform_client.post(
            reverse("platform:coupon-list"),
            _payload(code="PLATFORM5", discount_type=CouponType.FIXED, value="500.00"),
            format="json",
        )

        assert response.status_code == 201, response.data
        coupon = Coupon.objects.get(code="PLATFORM5")
        assert coupon.store_id is None

        listing = platform_client.get(reverse("platform:coupon-list"))
        assert listing.data["count"] == 1

    def test_a_platform_coupon_hides_from_store_lists(self, platform_client, dashboard_client):
        platform_client.post(
            reverse("platform:coupon-list"),
            _payload(code="PLATFORM5"),
            format="json",
        )

        listing = dashboard_client.get(reverse("dashboard:coupon-list"))

        assert listing.data["count"] == 0

    def test_a_store_admin_cannot_reach_the_platform_surface(self, dashboard_client):
        response = dashboard_client.post(reverse("platform:coupon-list"), _payload(), format="json")
        assert response.status_code == 403


class TestCouponUse:
    def test_a_created_coupon_applies_to_a_cart(self, dashboard_client, auth_client, store):
        dashboard_client.post(reverse("dashboard:coupon-list"), _payload(), format="json")

        _, variant = catalog_services.create_product(
            store=store,
            name="Margherita",
            price="12000.00",
            stock_qty=5,
            status=ProductStatus.ACTIVE,
        )
        cart = auth_client.post(reverse("cart:cart-list"), {"store": str(store.id)}, format="json")
        auth_client.post(
            reverse("cart:cart-items", kwargs={"pk": cart.data["id"]}),
            {"variant": str(variant.id), "quantity": 1},
            format="json",
        )

        response = auth_client.post(
            reverse("cart:cart-coupon", kwargs={"pk": cart.data["id"]}),
            {"code": "TAKE10"},
            format="json",
        )

        assert response.status_code == 200, response.data
        assert response.data["discount_total"] == "1200.00"
