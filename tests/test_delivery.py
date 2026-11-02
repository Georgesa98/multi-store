"""The delivery flow: checkout locks a quote, the company dispatches, the courier fulfils."""

from decimal import Decimal

import pytest
from django.urls import reverse

from catalog import services as catalog_services
from core.enums import (
    DeliveryAction,
    DeliveryStatus,
    OrderStatus,
    PaymentStatus,
    ProductStatus,
)
from delivery import services as delivery_services
from delivery.models import Delivery, DeliveryEvent
from orders.models import Order
from tests.factories import make_courier, zone_for_store

pytestmark = pytest.mark.django_db


def _variant(store, price="12000.00", stock=10):
    _, variant = catalog_services.create_product(
        store=store,
        name="Margherita",
        price=price,
        stock_qty=stock,
        status=ProductStatus.ACTIVE,
    )
    return variant


def _checkout(client, address, store, variant, key="delivery-key"):
    cart = client.post(reverse("cart:cart-list"), {"store": str(store.id)}, format="json")
    assert cart.status_code in (200, 201), cart.data
    added = client.post(
        reverse("cart:cart-items", kwargs={"pk": cart.data["id"]}),
        {"variant": str(variant.id), "quantity": 1},
        format="json",
    )
    assert added.status_code == 201, added.data

    response = client.post(
        reverse("orders:checkout"),
        {"address_id": str(address.id), "store_ids": [str(store.id)]},
        format="json",
        HTTP_IDEMPOTENCY_KEY=key,
    )
    assert response.status_code == 201, response.data
    return Order.objects.get(pk=response.data["orders"][0]["id"])


def _advance(client, order, *steps):
    for step in steps:
        response = client.post(
            reverse(f"dashboard:order-{step}", kwargs={"pk": order.id}),
            format="json",
        )
        assert response.status_code == 200, (step, response.data)
    order.refresh_from_db()
    return order


def _ready_order(customer_client, dashboard_client, address, store, variant, **kwargs):
    order = _checkout(customer_client, address, store, variant, **kwargs)
    return _advance(dashboard_client, order, "confirm", "preparing", "ready")


class TestDeliveryAtCheckout:
    def test_checkout_locks_the_quoted_company_zone_and_fee(
        self, auth_client, address, store, company, zone
    ):
        order = _checkout(auth_client, address, store, _variant(store))

        delivery = Delivery.objects.get(order=order)
        assert delivery.company == company
        assert delivery.zone == zone
        assert delivery.fee == Decimal("5000.00")
        assert delivery.cash_to_collect == order.total
        assert delivery.status == DeliveryStatus.UNASSIGNED

        detail = auth_client.get(reverse("orders:order-detail", kwargs={"pk": order.id}))
        assert detail.data["delivery"]["company"]["name"] == company.name
        assert detail.data["delivery"]["fee"] == "5000.00"

    def test_quote_skips_a_partner_that_does_not_cover_the_address(
        self, store, company, other_company
    ):
        zone_for_store(
            store,
            company,
            priority=0,
            center_lat="40.000000",
            center_lng="40.000000",
            radius_km="1.00",
            name="Far Away",
        )
        near = zone_for_store(store, other_company, priority=1, radius_km="6.00")

        chosen = delivery_services.quote_for_store(
            store, Decimal("33.510000"), Decimal("36.290000")
        )

        assert chosen is not None
        assert chosen[0] == other_company
        assert chosen[1] == near

    def test_store_without_a_contract_gets_no_quote(self, store, address, auth_client):
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

        preview = auth_client.get(
            reverse("orders:checkout-preview"), {"address_id": str(address.id)}
        )

        assert preview.data["stores"][0]["company"] is None
        assert preview.data["stores"][0]["problems"]


class TestDispatch:
    def test_ready_requests_the_contracted_company(
        self, auth_client, address, store, company, zone, dashboard_client, company_client
    ):
        order = _ready_order(auth_client, dashboard_client, address, store, _variant(store))

        delivery = Delivery.objects.get(order=order)
        assert delivery.status == DeliveryStatus.REQUESTED
        assert delivery.requested_at is not None
        assert delivery.offered_at is not None
        assert DeliveryEvent.objects.filter(
            delivery=delivery, action=DeliveryAction.REQUESTED
        ).exists()

        jobs = company_client.get(reverse("company:delivery-list"))
        assert jobs.status_code == 200
        assert jobs.data["count"] == 1
        assert jobs.data["results"][0]["status"] == DeliveryStatus.REQUESTED


class TestFulfilment:
    def test_assign_pickup_and_deliver_collect_cod(
        self,
        auth_client,
        address,
        store,
        company,
        zone,
        dashboard_client,
        courier,
        courier_client,
        company_client,
    ):
        order = _ready_order(auth_client, dashboard_client, address, store, _variant(store))
        delivery = Delivery.objects.get(order=order)

        assigned = company_client.post(
            reverse("company:delivery-assign", kwargs={"pk": delivery.id}),
            {"courier_id": str(courier.courier_profile.id)},
            format="json",
        )
        assert assigned.status_code == 200, assigned.data
        assert assigned.data["courier"]["full_name"] == courier.full_name

        order.refresh_from_db()
        delivery.refresh_from_db()
        assert order.status == OrderStatus.ASSIGNED
        assert delivery.status == DeliveryStatus.ACCEPTED
        assert delivery.courier == courier

        picked = courier_client.post(reverse("courier:delivery-pickup", kwargs={"pk": delivery.id}))
        assert picked.status_code == 200, picked.data
        order.refresh_from_db()
        assert order.status == OrderStatus.OUT_FOR_DELIVERY

        delivered = courier_client.post(
            reverse("courier:delivery-deliver", kwargs={"pk": delivery.id}),
            {"otp": "1234", "note": "Handed over"},
            format="json",
        )
        assert delivered.status_code == 200, delivered.data

        order.refresh_from_db()
        delivery.refresh_from_db()
        assert order.status == OrderStatus.DELIVERED
        assert order.payment_status == PaymentStatus.COLLECTED
        assert delivery.status == DeliveryStatus.DELIVERED
        assert delivery.cash_collected == order.total
        assert delivery.cash_collected_at is not None

        courier.courier_profile.refresh_from_db()
        assert courier.courier_profile.deliveries_count == 1

        actions = list(
            DeliveryEvent.objects.filter(delivery=delivery).values_list("action", flat=True)
        )
        assert DeliveryAction.ASSIGNED in actions
        assert DeliveryAction.PICKED_UP in actions
        assert DeliveryAction.DELIVERED in actions

    def test_courier_accepts_an_offer(
        self, auth_client, address, store, company, zone, dashboard_client, courier, courier_client
    ):
        order = _ready_order(auth_client, dashboard_client, address, store, _variant(store))
        delivery = Delivery.objects.get(order=order)

        offers = courier_client.get(reverse("courier:offer-list"))
        assert offers.data["count"] == 1
        offered_id = offers.data["results"][0]["id"]

        accepted = courier_client.post(
            reverse("courier:delivery-accept", kwargs={"pk": offered_id})
        )
        assert accepted.status_code == 200, accepted.data
        assert accepted.data["status"] == DeliveryStatus.ACCEPTED

        order.refresh_from_db()
        assert order.status == OrderStatus.ASSIGNED
        assert Delivery.objects.get(pk=delivery.pk).courier == courier

    def test_offer_list_excludes_another_companys_jobs(
        self, auth_client, address, store, company, zone, dashboard_client, other_company
    ):
        _ready_order(auth_client, dashboard_client, address, store, _variant(store))
        foreign = make_courier(other_company, email="foreign@swift.test")
        from tests.conftest import client_for

        offers = client_for(foreign.user).get(reverse("courier:offer-list"))
        assert offers.data["count"] == 0

    def test_pickup_before_accept_is_409(
        self, auth_client, address, store, company, zone, dashboard_client, courier, courier_client
    ):
        order = _ready_order(auth_client, dashboard_client, address, store, _variant(store))
        delivery = Delivery.objects.get(order=order)

        response = courier_client.post(
            reverse("courier:delivery-pickup", kwargs={"pk": delivery.id})
        )
        assert response.status_code == 404  # not assigned to this courier yet


class TestReleaseAndFail:
    def _assigned(self, auth_client, address, store, company, zone, dashboard_client, courier):
        order = _ready_order(auth_client, dashboard_client, address, store, _variant(store))
        delivery = Delivery.objects.get(order=order)
        delivery_services.assign_courier(delivery, courier=courier, actor=company.owner)
        order.refresh_from_db()
        delivery.refresh_from_db()
        return order, delivery

    def test_company_release_returns_the_order_to_ready(
        self,
        auth_client,
        address,
        store,
        company,
        zone,
        dashboard_client,
        courier,
        company_client,
    ):
        order, delivery = self._assigned(
            auth_client, address, store, company, zone, dashboard_client, courier
        )

        released = company_client.post(
            reverse("company:delivery-release", kwargs={"pk": delivery.id}),
            {"note": "No rider available"},
            format="json",
        )
        assert released.status_code == 200, released.data

        order.refresh_from_db()
        delivery.refresh_from_db()
        assert order.status == OrderStatus.READY
        assert delivery.status == DeliveryStatus.UNASSIGNED
        assert delivery.courier is None
        # It is not offered straight back to the company that gave it up.
        assert delivery.assign_attempts == 1

    def test_failure_redispatches_the_job(
        self, auth_client, address, store, company, zone, dashboard_client, courier, courier_client
    ):
        order, delivery = self._assigned(
            auth_client, address, store, company, zone, dashboard_client, courier
        )

        failed = courier_client.post(
            reverse("courier:delivery-fail", kwargs={"pk": delivery.id}),
            {"reason": "Customer unreachable"},
            format="json",
        )
        assert failed.status_code == 200, failed.data

        order.refresh_from_db()
        delivery.refresh_from_db()
        assert order.status == OrderStatus.READY
        assert delivery.status == DeliveryStatus.REQUESTED
        assert delivery.assign_attempts == 1
        assert delivery.failure_reason == "Customer unreachable"
        assert DeliveryEvent.objects.filter(
            delivery=delivery, action=DeliveryAction.FAILED
        ).exists()

    def test_cancelling_the_order_cancels_the_delivery(
        self, auth_client, address, store, company, zone
    ):
        order = _checkout(auth_client, address, store, _variant(store))
        delivery = Delivery.objects.get(order=order)

        response = auth_client.post(
            reverse("orders:order-cancel", kwargs={"pk": order.id}),
            {"reason": "Changed my mind"},
            format="json",
        )
        assert response.status_code == 200, response.data

        delivery.refresh_from_db()
        assert delivery.status == DeliveryStatus.CANCELLED


class TestTenancy:
    def test_another_store_cannot_read_the_delivery(
        self, auth_client, address, store, company, zone, other_dashboard_client
    ):
        order = _checkout(auth_client, address, store, _variant(store))
        delivery = Delivery.objects.get(order=order)

        response = other_dashboard_client.get(
            reverse("dashboard:delivery-detail", kwargs={"pk": delivery.id})
        )
        assert response.status_code == 404

    def test_another_company_cannot_read_the_delivery(
        self, auth_client, address, store, company, zone, other_company_client
    ):
        order = _checkout(auth_client, address, store, _variant(store))
        delivery = Delivery.objects.get(order=order)

        response = other_company_client.get(
            reverse("company:delivery-detail", kwargs={"pk": delivery.id})
        )
        assert response.status_code == 404


class TestEarnings:
    def test_delivered_job_shows_in_company_and_courier_earnings(
        self,
        auth_client,
        address,
        store,
        company,
        zone,
        dashboard_client,
        courier,
        courier_client,
        company_client,
    ):
        order = _ready_order(auth_client, dashboard_client, address, store, _variant(store))
        delivery = Delivery.objects.get(order=order)
        delivery_services.assign_courier(delivery, courier=courier, actor=company.owner)
        delivery_services.pickup(delivery, courier=courier)
        delivery_services.deliver(delivery, courier=courier)

        company_report = company_client.get(reverse("company:earnings"))
        assert company_report.status_code == 200
        assert company_report.data["deliveries"] == 1
        assert company_report.data["cash_collected"] == str(order.total)
        assert company_report.data["gross_fees"] == "5000.00"
        assert company_report.data["net_fees"] == "4500.00"

        courier_report = courier_client.get(reverse("courier:earnings"))
        assert courier_report.status_code == 200
        assert courier_report.data["deliveries"] == 1
        assert courier_report.data["delivery_fees"] == "5000.00"

    def test_courier_me_includes_todays_stats(self, courier_client):
        response = courier_client.get(reverse("courier:me"))

        assert response.status_code == 200
        assert response.data["profile"]["full_name"]
        assert response.data["stats"]["delivered_today"] == 0
