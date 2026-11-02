"""Settlement: weekly payouts per store/company and their ledger movement."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.urls import reverse

from analytics import services as analytics_services
from analytics.models import LedgerEntry, Payout
from catalog import services as catalog_services
from core.enums import LedgerKind, OrderStatus, PayoutStatus, ProductStatus
from core.exceptions import Conflict
from delivery import services as delivery_services
from delivery.models import Delivery
from orders import services as order_services
from orders.models import Order

pytestmark = pytest.mark.django_db


def _checkout(client, address, store, variant, key):
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
            reverse(f"dashboard:order-{step}", kwargs={"pk": order.id}), format="json"
        )
        assert response.status_code == 200, (step, response.data)
    order.refresh_from_db()
    return order


def _delivered(auth_client, dashboard_client, address, store, company, courier, variant, key):
    order = _checkout(auth_client, address, store, variant, key)
    _advance(dashboard_client, order, "confirm", "preparing", "ready")
    delivery = Delivery.objects.get(order=order)
    delivery_services.assign_courier(delivery, courier=courier, actor=company.owner)
    delivery_services.pickup(delivery, courier=courier)
    delivery_services.deliver(delivery, courier=courier)
    order.refresh_from_db()
    return order


@pytest.fixture
def delivered(auth_client, dashboard_client, address, store, company, zone, courier):
    _, variant = catalog_services.create_product(
        store=store,
        name="Margherita",
        price="12000.00",
        stock_qty=10,
        status=ProductStatus.ACTIVE,
    )
    order = _delivered(
        auth_client,
        dashboard_client,
        address,
        store,
        company,
        courier,
        variant,
        "payout-key",
    )
    return {"order": order, "store": store, "company": company, "variant": variant}


class TestMaterialisation:
    def test_one_payout_per_store_and_company(self, delivered):
        week = analytics_services.week_start()

        payouts = analytics_services.materialise_payouts(week)

        assert len(payouts) == 1
        payout = payouts[0]
        assert payout.store_id == delivered["store"].id
        assert payout.company_id == delivered["company"].id
        assert payout.period_start == week
        assert payout.period_end == week + timedelta(days=6)
        assert payout.deliveries == 1
        assert payout.cash_collected == Decimal("17000.00")
        assert payout.delivery_fees == Decimal("5000.00")
        assert payout.platform_commission == Decimal("1700.00")
        assert payout.store_net == Decimal("10800.00")
        assert payout.company_net == Decimal("4500.00")
        assert payout.status == PayoutStatus.PENDING
        assert payout.cash_collected == (
            payout.store_net + payout.company_net + payout.platform_commission
        )

    def test_materialising_twice_keeps_one_row(self, delivered):
        week = analytics_services.week_start()

        analytics_services.materialise_payouts(week)
        analytics_services.materialise_payouts(week)

        assert Payout.objects.filter(store=delivered["store"], period_start=week).count() == 1

    def test_a_refund_in_the_week_offsets_the_payout(self, delivered, super_admin):
        order_services.transition(
            order=delivered["order"], to_status=OrderStatus.REFUNDED, actor=super_admin
        )

        payout = analytics_services.materialise_payouts(analytics_services.week_start())[0]

        assert payout.cash_collected == Decimal("0.00")
        assert payout.platform_commission == Decimal("0.00")
        assert payout.store_net == Decimal("0.00")
        assert payout.company_net == Decimal("0.00")

    def test_the_command_normalises_to_the_monday(self, delivered):
        today = analytics_services.report_date()

        call_command("materialise_payouts", "--week", today.isoformat())

        assert Payout.objects.filter(
            store=delivered["store"], period_start=analytics_services.week_start(today)
        ).exists()


class TestStatusFlow:
    def test_settle_then_mark_paid_records_the_ledger_movement(self, delivered, platform_client):
        payout = analytics_services.materialise_payouts(analytics_services.week_start())[0]
        settle = reverse("platform:payout-settle", kwargs={"pk": payout.id})

        settled = platform_client.post(settle)

        assert settled.status_code == 200, settled.data
        assert settled.data["status"] == PayoutStatus.SETTLED
        assert settled.data["settled_at"] is not None

        paid = platform_client.post(reverse("platform:payout-mark-paid", kwargs={"pk": payout.id}))

        assert paid.status_code == 200, paid.data
        assert paid.data["status"] == PayoutStatus.PAID
        assert paid.data["paid_at"] is not None

        movement = LedgerEntry.objects.get(store=delivered["store"], kind=LedgerKind.PAYOUT)
        assert movement.gross == Decimal("10800.00")
        assert movement.net == Decimal("10800.00")
        assert movement.order_id is None

    def test_mark_paid_needs_a_settled_payout(self, delivered, platform_client):
        payout = analytics_services.materialise_payouts(analytics_services.week_start())[0]

        response = platform_client.post(
            reverse("platform:payout-mark-paid", kwargs={"pk": payout.id})
        )

        assert response.status_code == 409
        payout.refresh_from_db()
        assert payout.status == PayoutStatus.PENDING
        assert not LedgerEntry.objects.filter(kind=LedgerKind.PAYOUT).exists()

    def test_a_settled_week_is_not_rewritten(
        self,
        delivered,
        platform_client,
        auth_client,
        dashboard_client,
        address,
        company,
        courier,
    ):
        week = analytics_services.week_start()
        payout = analytics_services.materialise_payouts(week)[0]
        platform_client.post(reverse("platform:payout-settle", kwargs={"pk": payout.id}))

        second = _delivered(
            auth_client,
            dashboard_client,
            address,
            delivered["store"],
            company,
            courier,
            delivered["variant"],
            "payout-late",
        )
        assert second.status == OrderStatus.DELIVERED

        analytics_services.materialise_payouts(week)

        payout.refresh_from_db()
        assert payout.status == PayoutStatus.SETTLED
        assert payout.cash_collected == Decimal("17000.00")
        assert payout.store_net == Decimal("10800.00")

    def test_settling_twice_is_a_conflict(self, delivered):
        payout = analytics_services.materialise_payouts(analytics_services.week_start())[0]
        analytics_services.settle_payout(payout)
        payout.refresh_from_db()

        with pytest.raises(Conflict):
            analytics_services.settle_payout(payout)


class TestPayoutApi:
    def test_list_and_filters(self, delivered, platform_client):
        analytics_services.materialise_payouts(analytics_services.week_start())

        listing = platform_client.get(reverse("platform:payout-list"))
        assert listing.status_code == 200
        assert listing.data["count"] == 1
        assert listing.data["results"][0]["status"] == PayoutStatus.PENDING

        by_status = platform_client.get(reverse("platform:payout-list"), {"status": "settled"})
        assert by_status.data["count"] == 0

        by_store = platform_client.get(
            reverse("platform:payout-list"), {"store": str(delivered["store"].id)}
        )
        assert by_store.data["count"] == 1

        by_company = platform_client.get(
            reverse("platform:payout-list"), {"company": str(delivered["company"].id)}
        )
        assert by_company.data["count"] == 1

    def test_a_store_admin_cannot_read_payouts(self, dashboard_client):
        assert dashboard_client.get(reverse("platform:payout-list")).status_code == 403

    def test_a_paid_payout_does_not_inflate_revenue(self, delivered, platform_client):
        payout = analytics_services.materialise_payouts(analytics_services.week_start())[0]
        platform_client.post(reverse("platform:payout-settle", kwargs={"pk": payout.id}))
        platform_client.post(reverse("platform:payout-mark-paid", kwargs={"pk": payout.id}))

        revenue = platform_client.get(reverse("platform:insight-revenue"))

        row = revenue.data[-1]
        assert row["commission"] == "1700.00"
        assert row["gross"] == "17000.00"
