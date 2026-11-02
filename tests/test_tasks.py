"""Scheduled jobs: stale pending orders and the location-ping trail."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from catalog import services as catalog_services
from catalog.models import InventoryMovement, ProductVariant
from core.enums import InventoryReason, OrderStatus, ProductStatus
from delivery.models import DeliveryLocationPing
from delivery.tasks import prune_location_pings
from notifications.models import Notification
from orders.models import Order, OrderStatusEvent
from orders.tasks import cancel_stale_pending_orders

pytestmark = pytest.mark.django_db


def _pending_order(client, address, store, key, *, minutes_old=0, quantity=2):
    _, variant = catalog_services.create_product(
        store=store,
        name="Margherita",
        price="12000.00",
        stock_qty=10,
        status=ProductStatus.ACTIVE,
    )
    cart = client.post(reverse("cart:cart-list"), {"store": str(store.id)}, format="json")
    assert cart.status_code in (200, 201), cart.data
    added = client.post(
        reverse("cart:cart-items", kwargs={"pk": cart.data["id"]}),
        {"variant": str(variant.id), "quantity": quantity},
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
    order = Order.objects.get(pk=response.data["orders"][0]["id"])

    if minutes_old:
        backdated = timezone.now() - timedelta(minutes=minutes_old)
        Order.objects.filter(pk=order.pk).update(created_at=backdated)
        order.refresh_from_db()
    return order, variant


class TestStalePendingOrders:
    def test_an_unconfirmed_order_is_cancelled_and_its_stock_restored(
        self, auth_client, address, store, company, zone
    ):
        order, variant = _pending_order(auth_client, address, store, "stale-key", minutes_old=31)
        assert ProductVariant.objects.get(pk=variant.pk).stock_qty == 8

        assert cancel_stale_pending_orders() == 1

        order.refresh_from_db()
        assert order.status == OrderStatus.CANCELLED
        assert order.cancelled_at is not None
        assert "30 minutes" in order.cancel_reason

        assert ProductVariant.objects.get(pk=variant.pk).stock_qty == 10
        movement = InventoryMovement.objects.get(order=order, reason=InventoryReason.CANCEL_RETURN)
        assert movement.reason == InventoryReason.CANCEL_RETURN
        assert movement.delta == 2

        event = OrderStatusEvent.objects.get(order=order, to_status=OrderStatus.CANCELLED)
        assert event.actor is None
        assert event.actor_role == "system"

        assert Notification.objects.filter(user=order.customer, title="Order cancelled").exists()
        assert Notification.objects.filter(user=store.owner, title="Order cancelled").exists()

    def test_a_fresh_order_is_left_alone(self, auth_client, address, store, company, zone):
        order, variant = _pending_order(auth_client, address, store, "fresh-key", minutes_old=5)

        assert cancel_stale_pending_orders() == 0

        order.refresh_from_db()
        assert order.status == OrderStatus.PENDING
        assert ProductVariant.objects.get(pk=variant.pk).stock_qty == 8

    def test_a_confirmed_order_is_never_touched(
        self, auth_client, dashboard_client, address, store, company, zone
    ):
        order, _ = _pending_order(auth_client, address, store, "confirmed-key", minutes_old=45)
        confirmed = dashboard_client.post(
            reverse("dashboard:order-confirm", kwargs={"pk": order.id}), format="json"
        )
        assert confirmed.status_code == 200, confirmed.data

        assert cancel_stale_pending_orders() == 0

        order.refresh_from_db()
        assert order.status == OrderStatus.CONFIRMED

    def test_running_twice_cancels_once(self, auth_client, address, store, company, zone):
        _pending_order(auth_client, address, store, "twice-key", minutes_old=40)

        assert cancel_stale_pending_orders() == 1
        assert cancel_stale_pending_orders() == 0

        assert OrderStatusEvent.objects.filter(to_status=OrderStatus.CANCELLED).count() == 1


class TestPruneLocationPings:
    def test_only_pings_older_than_the_retention_window_go(
        self, auth_client, address, store, company, zone
    ):
        order, _ = _pending_order(auth_client, address, store, "ping-key")
        delivery = order.delivery

        old = DeliveryLocationPing.objects.create(
            delivery=delivery, lat="33.510000", lng="36.290000"
        )
        recent = DeliveryLocationPing.objects.create(
            delivery=delivery, lat="33.520000", lng="36.300000"
        )
        DeliveryLocationPing.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=31)
        )

        assert prune_location_pings() == 1

        assert not DeliveryLocationPing.objects.filter(pk=old.pk).exists()
        assert DeliveryLocationPing.objects.filter(pk=recent.pk).exists()
