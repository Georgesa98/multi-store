"""The order state machine: allowed moves, illegal moves, events, stock."""

from decimal import Decimal

import pytest
from django.urls import reverse

from catalog import services as catalog_services
from core.enums import OrderStatus, PaymentStatus, ProductStatus
from core.exceptions import InvalidTransition
from orders import services
from orders.models import CheckoutGroup, Order, OrderItem, OrderStatusEvent

pytestmark = pytest.mark.django_db


def _order(store, customer, *, status=OrderStatus.PENDING, suffix=1, with_item=False):
    group = CheckoutGroup.objects.create(customer=customer, address_snapshot={})
    order = Order.objects.create(
        store=store,
        group=group,
        customer=customer,
        number=f"{store.code}-{suffix:06d}",
        status=status,
        subtotal=Decimal("1000.00"),
        total=Decimal("1000.00"),
        currency=store.currency,
    )
    if with_item:
        _, variant = catalog_services.create_product(
            store=store,
            name=f"Item {suffix}",
            price="500.00",
            stock_qty=5,
            status=ProductStatus.ACTIVE,
        )
        OrderItem.objects.create(
            order=order,
            product=variant.product,
            variant=variant,
            name_snapshot=variant.product.name,
            variant_label_snapshot=variant.label,
            unit_price=Decimal("500.00"),
            quantity=2,
            line_total=Decimal("1000.00"),
        )
    return order


class TestAllowedTransitions:
    def test_store_admin_walks_pending_to_ready(self, dashboard_client, store, customer):
        order = _order(store, customer)

        for endpoint in ("confirm", "preparing", "ready"):
            response = dashboard_client.post(
                reverse(f"dashboard:order-{endpoint}", kwargs={"pk": order.id})
            )
            assert response.status_code == 200, (endpoint, response.data)

        order.refresh_from_db()
        assert order.status == OrderStatus.READY
        assert order.events.count() == 3
        assert [event.to_status for event in order.events.all()] == [
            OrderStatus.CONFIRMED,
            OrderStatus.PREPARING,
            OrderStatus.READY,
        ]

    def test_event_records_from_to_and_actor(self, dashboard_client, store, customer):
        order = _order(store, customer)

        dashboard_client.post(reverse("dashboard:order-confirm", kwargs={"pk": order.id}))

        event = OrderStatusEvent.objects.get(order=order)
        assert event.from_status == OrderStatus.PENDING
        assert event.to_status == OrderStatus.CONFIRMED
        assert event.actor_id == store.owner_id
        assert event.actor_role == "store_admin"

    def test_customer_cancels_pending_order(self, auth_client, customer, store):
        order = _order(store, customer)

        response = auth_client.post(
            reverse("orders:order-cancel", kwargs={"pk": order.id}),
            {"reason": "Changed my mind"},
            format="json",
        )

        assert response.status_code == 200, response.data
        order.refresh_from_db()
        assert order.status == OrderStatus.CANCELLED
        assert order.cancel_reason == "Changed my mind"
        assert order.cancelled_at is not None

    def test_customer_cancels_confirmed_order(self, auth_client, customer, store):
        # §9.2 allows customer cancellation while pending/confirmed.
        order = _order(store, customer, status=OrderStatus.CONFIRMED)

        response = auth_client.post(reverse("orders:order-cancel", kwargs={"pk": order.id}))

        assert response.status_code == 200, response.data

    def test_cancelling_restores_stock(self, dashboard_client, store, customer):
        order = _order(store, customer, with_item=True)
        variant = order.items.first().variant
        variant.refresh_from_db()
        assert variant.stock_qty == 5

        response = dashboard_client.post(
            reverse("dashboard:order-cancel", kwargs={"pk": order.id}),
            {"reason": "Out of ingredients"},
            format="json",
        )

        assert response.status_code == 200, response.data
        variant.refresh_from_db()
        assert variant.stock_qty == 7  # 5 + the 2 ordered

    def test_refunded_is_super_admin_only_and_keeps_stock(self, super_admin, store, customer):
        order = _order(store, customer, with_item=True)
        variant = order.items.first().variant

        with pytest.raises(InvalidTransition):
            services.transition(order=order, to_status=OrderStatus.REFUNDED, actor=customer)

        order = services.transition(order=order, to_status=OrderStatus.REFUNDED, actor=super_admin)
        assert order.status == OrderStatus.REFUNDED
        assert order.payment_status == PaymentStatus.UNPAID
        variant.refresh_from_db()
        assert variant.stock_qty == 5  # goods were delivered; stock is untouched


class TestIllegalTransitions:
    def test_pending_cannot_jump_to_preparing(self, dashboard_client, store, customer):
        order = _order(store, customer)

        response = dashboard_client.post(
            reverse("dashboard:order-preparing", kwargs={"pk": order.id})
        )

        assert response.status_code == 409
        order.refresh_from_db()
        assert order.status == OrderStatus.PENDING
        assert order.events.count() == 0

    def test_customer_cannot_confirm(self, auth_client, customer, store):
        order = _order(store, customer)

        response = auth_client.post(reverse("orders:order-cancel", kwargs={"pk": order.id}))
        assert response.status_code == 200

    def test_customer_cannot_move_to_confirmed(self, customer, store):
        order = _order(store, customer)

        with pytest.raises(InvalidTransition):
            services.transition(order=order, to_status=OrderStatus.CONFIRMED, actor=customer)

    def test_delivered_is_terminal(self, dashboard_client, store, customer):
        order = _order(store, customer, status=OrderStatus.DELIVERED)

        response = dashboard_client.post(
            reverse("dashboard:order-cancel", kwargs={"pk": order.id}),
            {"reason": "Too late"},
            format="json",
        )

        assert response.status_code == 409

    def test_assigning_without_a_delivery_is_422(self, dashboard_client, store, customer):
        order = _order(store, customer, status=OrderStatus.READY)

        from core.exceptions import BusinessRuleViolation

        with pytest.raises(BusinessRuleViolation):
            services.transition(order=order, to_status=OrderStatus.ASSIGNED, actor=store.owner)

    def test_staff_cannot_transition(self, staff_client, store, customer):
        order = _order(store, customer)

        response = staff_client.post(reverse("dashboard:order-confirm", kwargs={"pk": order.id}))

        assert response.status_code == 403

    def test_cross_store_transition_is_404(
        self, other_dashboard_client, other_store, store, customer
    ):
        order = _order(store, customer)

        response = other_dashboard_client.post(
            reverse("dashboard:order-confirm", kwargs={"pk": order.id})
        )

        assert response.status_code == 404

    def test_cannot_cancel_another_customers_order(self, auth_client, store, make_customer):
        other = make_customer(email="other@example.com")
        order = _order(store, other)

        response = auth_client.post(reverse("orders:order-cancel", kwargs={"pk": order.id}))

        assert response.status_code == 404
