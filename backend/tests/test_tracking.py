"""Live tracking: a 60 s ticket, a read-only socket, and best-effort fan-out."""

from types import SimpleNamespace

import pytest
from channels.db import database_sync_to_async
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.core.cache import cache
from django.urls import reverse

from catalog import services as catalog_services
from config.asgi import application
from core.enums import ProductStatus
from delivery import realtime
from delivery import services as delivery_services
from delivery.models import Delivery
from delivery.realtime import group_for
from delivery.tickets import read_ticket
from orders.models import Order

pytestmark = pytest.mark.django_db


async def _close_db():
    """The consumer checks access in a worker thread with its own connection."""
    from django.db import connections

    await database_sync_to_async(connections.close_all)()


def _variant(store, price="12000.00", stock=10):
    _, variant = catalog_services.create_product(
        store=store,
        name="Margherita",
        price=price,
        stock_qty=stock,
        status=ProductStatus.ACTIVE,
    )
    return variant


def _checkout(client, address, store, variant, key="tracking-key"):
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


@pytest.fixture(autouse=True)
def _clean_location_throttle():
    from django.core.cache import cache as django_cache

    django_cache.clear()
    yield
    django_cache.clear()


@pytest.fixture
def tracked(auth_client, dashboard_client, address, store, company, zone, courier):
    """A ready order already assigned to the courier: the socket's usual state."""
    order = _checkout(auth_client, address, store, _variant(store))
    _advance(dashboard_client, order, "confirm", "preparing", "ready")
    delivery = Delivery.objects.get(order=order)
    delivery_services.assign_courier(delivery, courier=courier, actor=company.owner)
    delivery.refresh_from_db()
    return SimpleNamespace(
        order=order,
        delivery=delivery,
        customer=order.customer,
        store=store,
        company=company,
        courier=courier,
    )


class TestTickets:
    def test_customer_ticket_is_a_minute_long_and_bound_to_the_delivery(self, tracked, auth_client):
        response = auth_client.get(
            reverse("orders:order-ws-ticket", kwargs={"pk": tracked.order.id})
        )

        assert response.status_code == 200, response.data
        assert response.data["expires_in"] == 60
        assert response.data["url"] == f"/ws/delivery/{tracked.delivery.id}/"

        claims = read_ticket(response.data["ticket"])
        assert claims["delivery"] == str(tracked.delivery.id)
        assert claims["sub"] == str(tracked.customer.id)
        assert claims["token_type"] == "tracking"
        assert claims["exp"] - claims["iat"] == 60

    def test_another_customer_cannot_get_the_ticket(self, tracked, other_customer):
        from tests.conftest import client_for

        response = client_for(other_customer).get(
            reverse("orders:order-ws-ticket", kwargs={"pk": tracked.order.id})
        )
        assert response.status_code == 404

    def test_store_and_company_and_courier_each_get_one(
        self, tracked, dashboard_client, company_client, courier_client
    ):
        store_ticket = dashboard_client.get(
            reverse("dashboard:order-ws-ticket", kwargs={"pk": tracked.order.id})
        )
        assert store_ticket.status_code == 200, store_ticket.data

        company_ticket = company_client.get(
            reverse("company:delivery-ws-ticket", kwargs={"pk": tracked.delivery.id})
        )
        assert company_ticket.status_code == 200, company_ticket.data

        courier_ticket = courier_client.get(
            reverse("courier:delivery-ws-ticket", kwargs={"pk": tracked.delivery.id})
        )
        assert courier_ticket.status_code == 200, courier_ticket.data

    def test_cross_tenant_ticket_is_404(
        self,
        tracked,
        other_dashboard_client,
        other_company_client,
        second_courier,
    ):
        from tests.conftest import client_for

        assert (
            other_dashboard_client.get(
                reverse("dashboard:order-ws-ticket", kwargs={"pk": tracked.order.id})
            ).status_code
            == 404
        )
        assert (
            other_company_client.get(
                reverse("company:delivery-ws-ticket", kwargs={"pk": tracked.delivery.id})
            ).status_code
            == 404
        )
        assert (
            client_for(second_courier)
            .get(reverse("courier:delivery-ws-ticket", kwargs={"pk": tracked.delivery.id}))
            .status_code
            == 404
        )


class TestSocket:
    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_customer_receives_a_fanned_out_location(self, tracked):
        from delivery.tickets import issue_ticket

        ticket = issue_ticket(user=tracked.customer, delivery=tracked.delivery)
        communicator = WebsocketCommunicator(
            application, f"/ws/delivery/{tracked.delivery.id}/?ticket={ticket}"
        )

        connected, _ = await communicator.connect()
        assert connected is True

        layer = get_channel_layer()
        await layer.group_send(
            group_for(tracked.delivery.id),
            {"type": "location", "lat": 33.51, "lng": 36.29, "at": "2026-01-01T00:00:00Z"},
        )

        message = await communicator.receive_json_from()
        assert message["type"] == "location"
        assert message["lat"] == 33.51

        await communicator.disconnect()
        await _close_db()

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_a_missing_ticket_is_rejected(self, tracked):
        communicator = WebsocketCommunicator(application, f"/ws/delivery/{tracked.delivery.id}/")

        connected, code = await communicator.connect()

        assert connected is False
        assert code == 4401
        await _close_db()

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_a_foreign_customer_is_refused(self, tracked, other_customer):
        from delivery.tickets import issue_ticket

        ticket = issue_ticket(user=other_customer, delivery=tracked.delivery)
        communicator = WebsocketCommunicator(
            application, f"/ws/delivery/{tracked.delivery.id}/?ticket={ticket}"
        )

        connected, code = await communicator.connect()

        assert connected is False
        assert code == 4403
        await _close_db()

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_a_ticket_for_another_delivery_is_refused(self, tracked):
        from delivery.tickets import issue_ticket

        ticket = issue_ticket(user=tracked.customer, delivery=tracked.delivery)
        communicator = WebsocketCommunicator(
            application, "/ws/delivery/00000000-0000-0000-0000-000000000000/?ticket=" + ticket
        )

        connected, code = await communicator.connect()

        assert connected is False
        assert code == 4401
        await _close_db()

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_store_admin_and_dispatcher_can_watch(self, tracked):
        from delivery.tickets import issue_ticket

        for user in (tracked.store.owner, tracked.company.owner, tracked.courier):
            ticket = issue_ticket(user=user, delivery=tracked.delivery)
            communicator = WebsocketCommunicator(
                application, f"/ws/delivery/{tracked.delivery.id}/?ticket={ticket}"
            )
            connected, _ = await communicator.connect()
            assert connected is True, user.email
            await communicator.disconnect()
        await _close_db()


class TestFanOut:
    def test_location_is_throttled_to_one_frame_a_second(self, tracked, monkeypatch):
        calls = []
        monkeypatch.setattr(realtime, "_send", lambda delivery_id, message: calls.append(message))

        for _ in range(3):
            delivery_services.record_location(
                delivery=tracked.delivery,
                courier=tracked.courier,
                lat="33.510000",
                lng="36.290000",
            )

        assert len(calls) == 1
        assert calls[0]["type"] == "location"

        cache.clear()
        delivery_services.record_location(
            delivery=tracked.delivery,
            courier=tracked.courier,
            lat="33.520000",
            lng="36.300000",
        )
        assert len(calls) == 2

    def test_a_status_change_is_broadcast(self, tracked, monkeypatch):
        calls = []
        monkeypatch.setattr(realtime, "_send", lambda delivery_id, message: calls.append(message))

        delivery_services.fail(tracked.delivery, actor=tracked.courier, reason="Nobody home")

        statuses = [message["status"] for message in calls if message["type"] == "status"]
        assert "failed" in statuses
