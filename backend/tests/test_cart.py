"""Cart rules: accumulate, stock caps, coupons, and customer scoping."""

from decimal import Decimal

import pytest
from django.urls import reverse

from cart.models import Cart
from catalog import services as catalog_services
from core.enums import CouponType, ProductStatus
from orders.models import Coupon
from tests.conftest import client_for

pytestmark = pytest.mark.django_db


def _product(store, name="Margherita", price="12000.00", stock=10):
    _product_row, variant = catalog_services.create_product(
        store=store,
        name=name,
        price=price,
        stock_qty=stock,
        status=ProductStatus.ACTIVE,
    )
    return variant


def _cart(client, store):
    response = client.post(reverse("cart:cart-list"), {"store": str(store.id)}, format="json")
    assert response.status_code in (200, 201), response.data
    return response.data


class TestCartLifecycle:
    def test_create_is_get_or_create(self, auth_client, store):
        first = auth_client.post(reverse("cart:cart-list"), {"store": str(store.id)}, format="json")
        second = auth_client.post(
            reverse("cart:cart-list"), {"store": str(store.id)}, format="json"
        )

        assert first.status_code == 201
        assert second.status_code == 200
        assert first.data["id"] == second.data["id"]
        assert Cart.objects.count() == 1

    def test_add_accumulates_and_reports_totals(self, auth_client, store):
        variant = _product(store, price="12000.00")
        cart = _cart(auth_client, store)

        first = auth_client.post(
            reverse("cart:cart-items", kwargs={"pk": cart["id"]}),
            {"variant": str(variant.id), "quantity": 1},
            format="json",
        )
        second = auth_client.post(
            reverse("cart:cart-items", kwargs={"pk": cart["id"]}),
            {"variant": str(variant.id), "quantity": 2},
            format="json",
        )

        assert first.status_code == 201, first.data
        assert second.status_code == 201, second.data
        assert second.data["quantity"] == 3
        assert second.data["line_total"] == "36000.00"

        listed = auth_client.get(reverse("cart:cart-list"))
        cart_row = listed.data["results"][0]
        assert cart_row["subtotal"] == "36000.00"
        assert cart_row["total"] == "36000.00"

    def test_cannot_exceed_stock(self, auth_client, store):
        variant = _product(store, stock=2)
        cart = _cart(auth_client, store)

        response = auth_client.post(
            reverse("cart:cart-items", kwargs={"pk": cart["id"]}),
            {"variant": str(variant.id), "quantity": 3},
            format="json",
        )

        assert response.status_code == 422

    def test_cannot_add_another_stores_product(self, auth_client, store, other_store):
        foreign_variant = _product(other_store)
        cart = _cart(auth_client, store)

        response = auth_client.post(
            reverse("cart:cart-items", kwargs={"pk": cart["id"]}),
            {"variant": str(foreign_variant.id), "quantity": 1},
            format="json",
        )

        assert response.status_code == 422

    def test_update_quantity_and_delete(self, auth_client, store):
        variant = _product(store)
        cart = _cart(auth_client, store)
        created = auth_client.post(
            reverse("cart:cart-items", kwargs={"pk": cart["id"]}),
            {"variant": str(variant.id), "quantity": 2},
            format="json",
        ).data

        patched = auth_client.patch(
            reverse(
                "cart:cart-item-detail",
                kwargs={"pk": cart["id"], "item_id": created["id"]},
            ),
            {"quantity": 5},
            format="json",
        )
        assert patched.status_code == 200
        assert patched.data["quantity"] == 5

        deleted = auth_client.delete(
            reverse(
                "cart:cart-item-detail",
                kwargs={"pk": cart["id"], "item_id": created["id"]},
            )
        )
        assert deleted.status_code == 204
        assert auth_client.get(reverse("cart:cart-list")).data["results"][0]["items"] == []

    def test_setting_quantity_to_zero_removes_the_row(self, auth_client, store):
        variant = _product(store)
        cart = _cart(auth_client, store)
        created = auth_client.post(
            reverse("cart:cart-items", kwargs={"pk": cart["id"]}),
            {"variant": str(variant.id), "quantity": 2},
            format="json",
        ).data

        response = auth_client.patch(
            reverse(
                "cart:cart-item-detail",
                kwargs={"pk": cart["id"], "item_id": created["id"]},
            ),
            {"quantity": 0},
            format="json",
        )

        assert response.status_code == 204
        assert auth_client.get(reverse("cart:cart-list")).data["results"][0]["items"] == []

    def test_clear_empties_the_cart(self, auth_client, store):
        variant = _product(store)
        cart = _cart(auth_client, store)
        auth_client.post(
            reverse("cart:cart-items", kwargs={"pk": cart["id"]}),
            {"variant": str(variant.id), "quantity": 2},
            format="json",
        )

        cleared = auth_client.post(reverse("cart:cart-clear", kwargs={"pk": cart["id"]}))

        assert cleared.status_code == 204
        assert auth_client.get(reverse("cart:cart-list")).data["results"][0]["items"] == []

    def test_carts_are_grouped_per_store(self, auth_client, store, other_store):
        _product(store)
        _product(other_store, name="Burger")

        _cart(auth_client, store)
        _cart(auth_client, other_store)

        listed = auth_client.get(reverse("cart:cart-list"))
        assert listed.data["count"] == 2
        assert {row["store"]["slug"] for row in listed.data["results"]} == {
            store.slug,
            other_store.slug,
        }

    def test_customer_cannot_touch_another_customers_cart(self, auth_client, store, make_customer):
        cart = _cart(auth_client, store)
        intruder = client_for(make_customer(email="intruder@example.com"))

        response = intruder.post(reverse("cart:cart-clear", kwargs={"pk": cart["id"]}))

        assert response.status_code == 404


class TestCartCoupons:
    def _coupon(self, store, **overrides):
        defaults = {
            "store": store,
            "code": "TAKE10",
            "discount_type": CouponType.PERCENT,
            "value": Decimal("10.00"),
        }
        defaults.update(overrides)
        return Coupon.objects.create(**defaults)

    def test_apply_and_remove_coupon(self, auth_client, store):
        variant = _product(store, price="10000.00")
        cart = _cart(auth_client, store)
        auth_client.post(
            reverse("cart:cart-items", kwargs={"pk": cart["id"]}),
            {"variant": str(variant.id), "quantity": 1},
            format="json",
        )
        self._coupon(store)

        applied = auth_client.post(
            reverse("cart:cart-coupon", kwargs={"pk": cart["id"]}),
            {"code": "TAKE10"},
            format="json",
        )

        assert applied.status_code == 200, applied.data
        assert applied.data["coupon"]["code"] == "TAKE10"
        assert applied.data["discount_total"] == "1000.00"
        assert applied.data["total"] == "9000.00"

        removed = auth_client.delete(reverse("cart:cart-coupon", kwargs={"pk": cart["id"]}))
        assert removed.status_code == 204
        assert auth_client.get(reverse("cart:cart-list")).data["results"][0]["coupon"] is None

    def test_unknown_code_is_422(self, auth_client, store):
        cart = _cart(auth_client, store)

        response = auth_client.post(
            reverse("cart:cart-coupon", kwargs={"pk": cart["id"]}),
            {"code": "NOPE"},
            format="json",
        )

        assert response.status_code == 422

    def test_minimum_subtotal_is_enforced(self, auth_client, store):
        variant = _product(store, price="1000.00")
        cart = _cart(auth_client, store)
        auth_client.post(
            reverse("cart:cart-items", kwargs={"pk": cart["id"]}),
            {"variant": str(variant.id), "quantity": 1},
            format="json",
        )
        self._coupon(store, min_order_total=Decimal("50000.00"))

        response = auth_client.post(
            reverse("cart:cart-coupon", kwargs={"pk": cart["id"]}),
            {"code": "TAKE10"},
            format="json",
        )

        assert response.status_code == 422

    def test_platform_coupon_applies_to_any_store(self, auth_client, store):
        variant = _product(store, price="10000.00")
        cart = _cart(auth_client, store)
        auth_client.post(
            reverse("cart:cart-items", kwargs={"pk": cart["id"]}),
            {"variant": str(variant.id), "quantity": 1},
            format="json",
        )
        self._coupon(None, code="PLATFORM5", discount_type=CouponType.FIXED, value=500)

        response = auth_client.post(
            reverse("cart:cart-coupon", kwargs={"pk": cart["id"]}),
            {"code": "PLATFORM5"},
            format="json",
        )

        assert response.status_code == 200, response.data
        assert response.data["discount_total"] == "500.00"
