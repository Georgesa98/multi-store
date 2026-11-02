"""Notifications: written with the event, read from the user's own inbox."""

import pytest
from django.urls import reverse

from catalog import services as catalog_services
from core.enums import NotificationType, OrderStatus, ProductStatus
from delivery import services as delivery_services
from delivery.models import Delivery
from notifications import services as notification_services
from notifications.models import Notification
from orders.models import Order

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


def _checkout(client, address, store, variant, key="notification-key"):
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


class TestOrderNotifications:
    def test_checkout_notifies_customer_and_store(self, auth_client, address, store, company, zone):
        order = _checkout(auth_client, address, store, _variant(store))

        customer_rows = Notification.objects.filter(user=order.customer)
        assert customer_rows.count() == 1
        assert customer_rows.get().title == "Order placed"
        assert customer_rows.get().data["order_number"] == order.number

        store_rows = Notification.objects.filter(user=store.owner)
        assert store_rows.count() == 1
        assert store_rows.get().title == "New order"

    def test_status_change_notifies_the_customer(
        self, auth_client, address, store, company, zone, dashboard_client
    ):
        order = _checkout(auth_client, address, store, _variant(store))
        Notification.objects.all().delete()

        _advance(dashboard_client, order, "confirm")

        row = Notification.objects.get(user=order.customer)
        assert row.title == "Order confirmed"
        assert row.data["status"] == OrderStatus.CONFIRMED

    def test_a_failed_attempt_does_not_repeat_ready(
        self,
        auth_client,
        address,
        store,
        company,
        zone,
        dashboard_client,
        courier,
    ):
        order = _checkout(auth_client, address, store, _variant(store))
        _advance(dashboard_client, order, "confirm", "preparing", "ready")
        delivery = Delivery.objects.get(order=order)
        delivery_services.assign_courier(delivery, courier=courier, actor=company.owner)

        delivery_services.fail(delivery, actor=courier, reason="Nobody home")

        ready_rows = Notification.objects.filter(user=order.customer, title="Order ready")
        assert ready_rows.count() == 1

    def test_delivery_pays_out_as_a_payment_notification(
        self, auth_client, address, store, company, zone, dashboard_client, courier
    ):
        order = _checkout(auth_client, address, store, _variant(store))
        _advance(dashboard_client, order, "confirm", "preparing", "ready")
        delivery = Delivery.objects.get(order=order)
        delivery_services.assign_courier(delivery, courier=courier, actor=company.owner)
        delivery_services.pickup(delivery, courier=courier)
        delivery_services.deliver(delivery, courier=courier)

        row = Notification.objects.get(user=order.customer, title="Order delivered")
        assert row.type == NotificationType.PAYMENT
        assert row.data["status"] == OrderStatus.DELIVERED

    def test_cancel_notifies_both_sides(self, auth_client, address, store, company, zone):
        order = _checkout(auth_client, address, store, _variant(store))
        Notification.objects.all().delete()

        response = auth_client.post(
            reverse("orders:order-cancel", kwargs={"pk": order.id}),
            {"reason": "Changed my mind"},
            format="json",
        )
        assert response.status_code == 200, response.data

        assert Notification.objects.filter(user=order.customer, title="Order cancelled").exists()
        assert Notification.objects.filter(user=store.owner, title="Order cancelled").exists()

    def test_dispatch_notifies_the_company_and_the_courier(
        self, auth_client, address, store, company, zone, dashboard_client, courier
    ):
        order = _checkout(auth_client, address, store, _variant(store))
        _advance(dashboard_client, order, "confirm", "preparing", "ready")

        assert Notification.objects.filter(user=company.owner, title="New delivery job").exists()

        delivery = Delivery.objects.get(order=order)
        delivery_services.assign_courier(delivery, courier=courier, actor=company.owner)

        assert Notification.objects.filter(user=courier, title="Delivery assigned").exists()


class TestInbox:
    def test_list_is_scoped_to_the_user(self, auth_client, customer, other_customer):
        notification_services.notify(customer, type=NotificationType.SYSTEM, title="Mine")
        notification_services.notify(other_customer, type=NotificationType.SYSTEM, title="Theirs")

        response = auth_client.get(reverse("notifications:notification-list"))

        assert response.status_code == 200
        assert response.data["count"] == 1
        assert response.data["results"][0]["title"] == "Mine"

    def test_unread_filter(self, auth_client, customer):
        notification_services.notify(customer, type=NotificationType.SYSTEM, title="New")
        read = notification_services.notify(customer, type=NotificationType.SYSTEM, title="Old")
        from django.utils import timezone

        read.read_at = timezone.now()
        read.save(update_fields=["read_at"])

        response = auth_client.get(reverse("notifications:notification-list"), {"unread": "true"})

        assert response.data["count"] == 1
        assert response.data["results"][0]["title"] == "New"

    def test_read_and_read_all(self, auth_client, customer):
        first = notification_services.notify(customer, type=NotificationType.SYSTEM, title="First")
        notification_services.notify(customer, type=NotificationType.SYSTEM, title="Second")

        single = auth_client.post(
            reverse("notifications:notification-read", kwargs={"pk": first.id})
        )
        assert single.status_code == 200
        assert single.data["read_at"] is not None

        bulk = auth_client.post(reverse("notifications:notification-read-all"))
        assert bulk.status_code == 200
        assert bulk.data["updated"] == 1
        assert Notification.objects.filter(user=customer, read_at__isnull=True).count() == 0

    def test_cannot_read_someone_elses_notification(self, auth_client, other_customer):
        foreign = notification_services.notify(
            other_customer, type=NotificationType.SYSTEM, title="Private"
        )

        response = auth_client.post(
            reverse("notifications:notification-read", kwargs={"pk": foreign.id})
        )
        assert response.status_code == 404

    def test_requires_authentication(self, api_client):
        assert api_client.get(reverse("notifications:notification-list")).status_code == 401
