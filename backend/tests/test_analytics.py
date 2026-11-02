"""Analytics: ledger rows at fulfilment, rollups, and the insight endpoints."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.urls import reverse

from analytics import services as analytics_services
from analytics.models import DailyProductStat, DailyStoreStat, LedgerEntry
from catalog import services as catalog_services
from core.enums import LedgerKind, OrderStatus, ProductStatus
from delivery import services as delivery_services
from delivery.models import Delivery
from orders import services as order_services
from orders.models import Order

pytestmark = pytest.mark.django_db


def _product(store, name="Margherita", price="12000.00"):
    product, variant = catalog_services.create_product(
        store=store,
        name=name,
        price=price,
        stock_qty=10,
        status=ProductStatus.ACTIVE,
    )
    return product, variant


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


@pytest.fixture
def delivered(auth_client, dashboard_client, address, store, company, zone, courier):
    product, variant = _product(store)
    order = _checkout(auth_client, address, store, variant, "analytics-key")
    _advance(dashboard_client, order, "confirm", "preparing", "ready")
    delivery = Delivery.objects.get(order=order)
    delivery_services.assign_courier(delivery, courier=courier, actor=company.owner)
    delivery_services.pickup(delivery, courier=courier)
    delivery_services.deliver(delivery, courier=courier)
    order.refresh_from_db()
    return {"order": order, "product": product, "delivery": delivery}


class TestLedger:
    def test_delivery_writes_a_sale_and_a_fee_commission(self, delivered):
        order = delivered["order"]

        sale = LedgerEntry.objects.get(order=order, kind=LedgerKind.SALE)
        assert sale.gross == Decimal("12000.00")
        assert sale.commission == Decimal("1200.00")
        assert sale.net == Decimal("10800.00")
        assert sale.net == sale.gross - sale.commission

        fee = LedgerEntry.objects.get(order=order, kind=LedgerKind.COMMISSION)
        assert fee.delivery_id == delivered["delivery"].id
        assert fee.gross == Decimal("5000.00")
        assert fee.commission == Decimal("500.00")
        assert fee.net == Decimal("4500.00")

    def test_the_sale_is_written_once(self, delivered):
        assert analytics_services.record_sale(delivered["order"]) == []
        assert (
            LedgerEntry.objects.filter(order=delivered["order"], kind=LedgerKind.SALE).count() == 1
        )

    def test_a_refund_negates_both_rows(self, delivered, super_admin):
        order = order_services.transition(
            order=delivered["order"],
            to_status=OrderStatus.REFUNDED,
            actor=super_admin,
            note="Damaged",
        )

        refunds = LedgerEntry.objects.filter(order=order, kind=LedgerKind.REFUND)
        assert refunds.count() == 2
        assert sum(entry.gross for entry in refunds) == Decimal("-17000.00")
        assert sum(entry.commission for entry in refunds) == Decimal("-1700.00")
        assert sum(entry.net for entry in refunds) == Decimal("-15300.00")

    def test_a_refund_happens_only_once(self, delivered, super_admin):
        order_services.transition(
            order=delivered["order"], to_status=OrderStatus.REFUNDED, actor=super_admin
        )

        assert analytics_services.record_refund(delivered["order"]) == []
        assert (
            LedgerEntry.objects.filter(order=delivered["order"], kind=LedgerKind.REFUND).count()
            == 2
        )


class TestRollups:
    def test_a_day_is_rolled_up_once(self, delivered, store):
        today = analytics_services.report_date()

        assert analytics_services.rollup_day(today) == 1
        assert analytics_services.rollup_day(today) == 1

        stat = DailyStoreStat.objects.get(store=store, date=today)
        assert stat.orders_placed == 1
        assert stat.orders_delivered == 1
        assert stat.orders_cancelled == 0
        assert stat.gross_sales == Decimal("12000.00")
        assert stat.net_sales == Decimal("12000.00")
        assert stat.delivery_fees == Decimal("5000.00")

        product_stat = DailyProductStat.objects.get(
            store=store, product=delivered["product"], date=today
        )
        assert product_stat.qty_sold == 1
        assert product_stat.revenue == Decimal("12000.00")
        assert DailyStoreStat.objects.filter(store=store, date=today).count() == 1

    def test_past_days_are_read_from_the_rollup(self, delivered, store, dashboard_client):
        yesterday = analytics_services.report_date() - timedelta(days=1)
        happened = analytics_services.day_bounds(yesterday)[0] + timedelta(hours=2)
        Order.objects.filter(pk=delivered["order"].pk).update(
            created_at=happened, delivered_at=happened
        )

        analytics_services.rollup_day(yesterday)

        response = dashboard_client.get(
            reverse("dashboard:insight-summary"),
            {"from": yesterday.isoformat(), "to": yesterday.isoformat()},
        )

        assert response.status_code == 200, response.data
        assert response.data["orders"] == 1
        assert response.data["gross_sales"] == "12000.00"
        assert response.data["to_date"] == yesterday.isoformat()

    def test_the_command_rolls_up_a_range(self, delivered, store):
        today = analytics_services.report_date()

        call_command("rollup_stats", "--from", today.isoformat(), "--to", today.isoformat())

        assert DailyStoreStat.objects.filter(store=store, date=today).exists()


class TestDashboardInsights:
    def test_summary_and_aov(self, delivered, dashboard_client):
        response = dashboard_client.get(reverse("dashboard:insight-summary"))

        assert response.status_code == 200, response.data
        assert response.data["orders"] == 1
        assert response.data["orders_delivered"] == 1
        assert response.data["gross_sales"] == "12000.00"
        assert response.data["delivery_fees"] == "5000.00"
        assert response.data["aov"] == "12000.00"

    def test_revenue_series(self, delivered, dashboard_client):
        response = dashboard_client.get(reverse("dashboard:insight-revenue"))

        assert response.status_code == 200
        row = response.data[-1]
        assert row["date"] == analytics_services.report_date().isoformat()
        assert row["gross_sales"] == "12000.00"
        assert row["net_sales"] == "12000.00"

    def test_top_products(self, delivered, dashboard_client):
        response = dashboard_client.get(reverse("dashboard:insight-top-products"))

        assert response.status_code == 200
        assert response.data[0]["name"] == "Margherita"
        assert response.data[0]["qty_sold"] == 1
        assert response.data[0]["revenue"] == "12000.00"

    def test_orders_by_status(self, delivered, dashboard_client):
        response = dashboard_client.get(reverse("dashboard:insight-orders-by-status"))

        counts = {row["status"]: row["count"] for row in response.data}
        assert counts[OrderStatus.DELIVERED] == 1
        assert counts[OrderStatus.PENDING] == 0

    def test_delivery_performance(self, delivered, dashboard_client):
        response = dashboard_client.get(reverse("dashboard:insight-delivery-performance"))

        assert response.status_code == 200
        assert response.data["completed"] == 1
        assert response.data["failed"] == 0
        assert response.data["failure_rate"] == "0.0000"

    def test_the_ledger_is_store_scoped(self, delivered, dashboard_client, other_dashboard_client):
        mine = dashboard_client.get(reverse("dashboard:ledger"))
        assert mine.data["count"] == 2

        theirs = other_dashboard_client.get(reverse("dashboard:ledger"))
        assert theirs.data["count"] == 0

        filtered = dashboard_client.get(reverse("dashboard:ledger"), {"kind": "sale"})
        assert filtered.data["count"] == 1

    def test_insights_are_store_scoped(self, delivered, other_dashboard_client):
        response = other_dashboard_client.get(reverse("dashboard:insight-summary"))
        assert response.data["orders"] == 0
        assert response.data["gross_sales"] == "0.00"


class TestPlatformInsights:
    def test_overview(self, delivered, platform_client):
        response = platform_client.get(reverse("platform:insight-overview"))

        assert response.status_code == 200
        assert response.data["orders"] == 1
        assert response.data["gmv"] == "17000.00"
        assert response.data["active_stores"] >= 1

    def test_revenue_is_the_platform_cut(self, delivered, platform_client):
        response = platform_client.get(reverse("platform:insight-revenue"))

        assert response.status_code == 200
        row = response.data[-1]
        assert row["date"] == analytics_services.report_date().isoformat()
        assert row["gross"] == "17000.00"
        assert row["commission"] == "1700.00"
        assert row["net"] == "15300.00"

    def test_platform_ledger_lists_every_store(self, delivered, platform_client, store):
        response = platform_client.get(reverse("platform:ledger"))
        assert response.data["count"] == 2

        by_store = platform_client.get(reverse("platform:ledger"), {"store": str(store.id)})
        assert by_store.data["count"] == 2

        by_kind = platform_client.get(reverse("platform:ledger"), {"kind": "sale"})
        assert by_kind.data["count"] == 1

    def test_a_store_admin_cannot_read_platform_insights(self, dashboard_client):
        assert dashboard_client.get(reverse("platform:insight-overview")).status_code == 403
