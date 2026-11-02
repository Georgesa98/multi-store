"""Checkout: one group, one order per store, correct money, idempotency, stock."""

from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from cart.models import Cart
from catalog import services as catalog_services
from catalog.models import InventoryMovement, ProductVariant
from core.enums import CouponType, InventoryReason, ProductStatus
from orders.models import CheckoutGroup, Coupon, CouponRedemption, Order, OrderItem
from tests.conftest import client_for
from tests.factories import zone_for_store

pytestmark = pytest.mark.django_db


def _product(store, name="Margherita", price="12000.00", stock=10):
    _, variant = catalog_services.create_product(
        store=store,
        name=name,
        price=price,
        stock_qty=stock,
        status=ProductStatus.ACTIVE,
    )
    return variant


def _zone(store, company, fee="5000.00", min_order_total="0.00"):
    return zone_for_store(store, company, fee=fee, min_order_total=min_order_total)


def _cart_with(client, store, variant, quantity=1):
    cart = client.post(reverse("cart:cart-list"), {"store": str(store.id)}, format="json")
    assert cart.status_code in (200, 201), cart.data
    item = client.post(
        reverse("cart:cart-items", kwargs={"pk": cart.data["id"]}),
        {"variant": str(variant.id), "quantity": quantity},
        format="json",
    )
    assert item.status_code == 201, item.data
    return cart.data


def _checkout(client, address, stores, key="key-1", **extra):
    payload = {
        "address_id": str(address.id),
        "store_ids": [str(store.id) for store in stores],
    }
    payload.update(extra)
    return client.post(
        reverse("orders:checkout"),
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY=key,
    )


class TestMultiStoreCheckout:
    def test_one_group_one_order_per_store(
        self, auth_client, customer, address, store, other_store, company, other_company
    ):
        _zone(store, company, fee="5000.00")
        _zone(other_store, other_company, fee="3000.00")
        first = _product(store, price="12000.00", stock=10)
        second = _product(other_store, name="Burger", price="8000.00", stock=10)

        _cart_with(auth_client, store, first, 2)
        _cart_with(auth_client, other_store, second, 1)

        response = _checkout(auth_client, address, [store, other_store], notes="Ring twice")

        assert response.status_code == 201, response.data
        group = CheckoutGroup.objects.get(pk=response.data["id"])
        assert group.customer == customer
        assert group.address_snapshot["line1"] == address.line1
        assert group.notes == "Ring twice"

        orders = list(Order.objects.filter(group=group).order_by("store__name"))
        assert len(orders) == 2
        by_store = {order.store_id: order for order in orders}
        assert set(by_store) == {store.id, other_store.id}

        pizza = by_store[store.id]
        burger = by_store[other_store.id]
        assert pizza.number.startswith(f"{store.code}-")
        assert burger.number.startswith(f"{other_store.code}-")
        assert pizza.subtotal == Decimal("24000.00")
        assert pizza.delivery_fee == Decimal("5000.00")
        assert pizza.total == Decimal("29000.00")
        assert burger.subtotal == Decimal("8000.00")
        assert burger.delivery_fee == Decimal("3000.00")
        assert burger.total == Decimal("11000.00")
        assert pizza.currency == "SYP"

        # Stock moved through append-only `sale` movements tied to the order.
        assert ProductVariant.objects.get(pk=first.pk).stock_qty == 8
        movement = InventoryMovement.objects.get(order=pizza, variant=first)
        assert movement.reason == InventoryReason.SALE
        assert movement.delta == -2

        assert OrderItem.objects.filter(order=pizza).count() == 1
        assert Cart.objects.filter(customer=customer).count() == 0

    def test_order_invariants(self, auth_client, address, store, company):
        _zone(store, company)
        variant = _product(store, price="12000.00", stock=5)
        _cart_with(auth_client, store, variant, 2)

        response = _checkout(auth_client, address, [store])

        assert response.status_code == 201, response.data
        order = Order.objects.get(group_id=response.data["id"])
        assert order.subtotal == sum(item.line_total for item in order.items.all())
        assert (
            order.total
            == order.subtotal + order.delivery_fee + order.tax_total - order.discount_total
        )

    def test_idempotency_replay_returns_the_same_group(self, auth_client, address, store, company):
        _zone(store, company)
        variant = _product(store)
        _cart_with(auth_client, store, variant, 1)

        first = _checkout(auth_client, address, [store], key="same-key")
        second = _checkout(auth_client, address, [store], key="same-key")

        assert first.status_code == 201
        assert second.status_code == 200
        assert first.data["id"] == second.data["id"]
        assert CheckoutGroup.objects.count() == 1
        assert Order.objects.count() == 1

    def test_missing_idempotency_key_is_rejected(self, auth_client, address, store, company):
        _zone(store, company)
        variant = _product(store)
        _cart_with(auth_client, store, variant, 1)

        response = auth_client.post(
            reverse("orders:checkout"),
            {"address_id": str(address.id), "store_ids": [str(store.id)]},
            format="json",
        )

        assert response.status_code == 422
        assert CheckoutGroup.objects.count() == 0

    def test_replaying_another_customers_key_conflicts(
        self, auth_client, address, store, company, make_customer
    ):
        _zone(store, company)
        variant = _product(store)
        _cart_with(auth_client, store, variant, 1)
        _checkout(auth_client, address, [store], key="shared-key")

        other = make_customer(email="other@example.com")
        other_address = other.addresses.create(
            line1="Elsewhere",
            city="Damascus",
            lat=Decimal("33.510000"),
            lng=Decimal("36.290000"),
        )
        intruder = client_for(other)
        _cart_with(intruder, store, variant, 1)

        response = _checkout(intruder, other_address, [store], key="shared-key")

        assert response.status_code == 409

    def test_another_customers_address_is_404(self, auth_client, store, company, make_customer):
        _zone(store, company)
        variant = _product(store)
        _cart_with(auth_client, store, variant, 1)
        other = make_customer(email="other@example.com")
        foreign_address = other.addresses.create(
            line1="Elsewhere", city="Damascus", lat=Decimal("33.510000"), lng=Decimal("36.290000")
        )

        response = _checkout(auth_client, foreign_address, [store])

        assert response.status_code == 404

    def test_empty_cart_is_422(self, auth_client, address, store, company):
        _zone(store, company)

        response = _checkout(auth_client, address, [store])

        assert response.status_code == 422

    def test_outside_every_zone_is_422(self, auth_client, address, store):
        variant = _product(store)
        _cart_with(auth_client, store, variant, 1)

        response = _checkout(auth_client, address, [store])

        assert response.status_code == 422

    def test_minimum_order_total_is_422(self, auth_client, address, store, company):
        _zone(store, company, min_order_total="50000.00")
        variant = _product(store, price="1000.00")
        _cart_with(auth_client, store, variant, 1)

        response = _checkout(auth_client, address, [store])

        assert response.status_code == 422

    def test_cancelled_checkout_restores_nothing(self, auth_client, address, store, company):
        """A failed checkout must not leave a group or a decremented stock."""
        _zone(store, company, min_order_total="50000.00")
        variant = _product(store, price="1000.00", stock=5)
        _cart_with(auth_client, store, variant, 2)

        _checkout(auth_client, address, [store])

        assert CheckoutGroup.objects.count() == 0
        assert ProductVariant.objects.get(pk=variant.pk).stock_qty == 5


class TestCouponAtCheckout:
    def test_discount_is_applied_and_redemption_written(self, auth_client, address, store, company):
        _zone(store, company)
        variant = _product(store, price="10000.00")
        _cart_with(auth_client, store, variant, 1)
        coupon = Coupon.objects.create(
            store=store,
            code="TAKE10",
            discount_type=CouponType.PERCENT,
            value=Decimal("10.00"),
        )
        auth_client.post(
            reverse("cart:cart-coupon", kwargs={"pk": Cart.objects.get().id}),
            {"code": "TAKE10"},
            format="json",
        )

        response = _checkout(auth_client, address, [store])

        assert response.status_code == 201, response.data
        order = Order.objects.get(group_id=response.data["id"])
        assert order.discount_total == Decimal("1000.00")
        assert order.total == Decimal("14000.00")  # 10000 + 5000 - 1000

        redemption = CouponRedemption.objects.get(order=order)
        assert redemption.coupon == coupon
        assert redemption.discount_amount == Decimal("1000.00")
        coupon.refresh_from_db()
        assert coupon.used_count == 1


class TestPreview:
    def test_preview_lists_store_quotes(self, auth_client, customer, address, store, company):
        _zone(store, company, fee="5000.00")
        variant = _product(store, price="12000.00")
        _cart_with(auth_client, store, variant, 2)

        response = auth_client.get(
            reverse("orders:checkout-preview"), {"address_id": str(address.id)}
        )

        assert response.status_code == 200, response.data
        assert response.data["problems"] == []
        row = response.data["stores"][0]
        assert row["subtotal"] == "24000.00"
        assert row["delivery_fee"] == "5000.00"
        assert row["total"] == "29000.00"
        assert row["zone"]["eta_minutes"] == 30

    def test_preview_reports_problems(self, auth_client, address, store):
        variant = _product(store)
        _cart_with(auth_client, store, variant, 1)

        response = auth_client.get(
            reverse("orders:checkout-preview"), {"address_id": str(address.id)}
        )

        assert response.data["problems"]


@pytest.mark.django_db(transaction=True)
def test_concurrent_checkout_cannot_oversell(store, company, make_customer):
    """Two threads, one unit of stock: exactly one checkout wins."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    _zone(store, company)
    variant = _product(store, price="1000.00", stock=1)

    shoppers = [
        make_customer(email="a@example.com", full_name="A"),
        make_customer(email="b@example.com", full_name="B"),
    ]
    addresses = []
    carts = []
    for index, shopper in enumerate(shoppers):
        addresses.append(
            shopper.addresses.create(
                line1=f"{index} Main Street",
                city="Damascus",
                lat=Decimal("33.510000"),
                lng=Decimal("36.290000"),
            )
        )
        client = client_for(shopper)
        cart = client.post(reverse("cart:cart-list"), {"store": str(store.id)}, format="json")
        client.post(
            reverse("cart:cart-items", kwargs={"pk": cart.data["id"]}),
            {"variant": str(variant.id), "quantity": 1},
            format="json",
        )
        carts.append(cart.data["id"])

    from rest_framework_simplejwt.tokens import RefreshToken

    tokens = [str(RefreshToken.for_user(shopper).access_token) for shopper in shoppers]
    barrier = threading.Barrier(2)

    def run(index):
        from django.db import connections

        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens[index]}")
        barrier.wait()
        try:
            return client.post(
                reverse("orders:checkout"),
                {
                    "address_id": str(addresses[index].id),
                    "store_ids": [str(store.id)],
                },
                format="json",
                HTTP_IDEMPOTENCY_KEY=f"concurrent-{index}",
            ).status_code
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = sorted(pool.map(run, [0, 1]))

    assert results == [201, 422]
    assert Order.objects.count() == 1
    assert ProductVariant.objects.get(pk=variant.pk).stock_qty == 0
    assert (
        InventoryMovement.objects.filter(variant=variant, reason=InventoryReason.SALE).count() == 1
    )
