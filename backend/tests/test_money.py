"""No float ever appears in a money field of a serialized response."""

import json
import re

import pytest
from django.urls import reverse

from catalog import services as catalog_services
from core.enums import ProductStatus
from tests.factories import zone_for_store

pytestmark = pytest.mark.django_db

MONEY_PATTERN = re.compile(r"^-?\d+\.\d{2}$")


def _floats(node, path="$"):
    found = []
    if isinstance(node, float):
        found.append(path)
    elif isinstance(node, dict):
        for key, value in node.items():
            found += _floats(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found += _floats(value, f"{path}[{index}]")
    return found


def _assert_no_floats(response):
    payload = json.loads(response.content)
    assert _floats(payload) == []
    return payload


def _setup(client, address, store, company):
    zone_for_store(
        store,
        company,
        center_lat="33.510000",
        center_lng="36.290000",
        radius_km="6.00",
        fee="5000.00",
        min_order_total="0.00",
        eta_minutes=30,
    )
    _, variant = catalog_services.create_product(
        store=store,
        name="Margherita",
        price="12000.00",
        stock_qty=10,
        status=ProductStatus.ACTIVE,
    )
    cart = client.post(reverse("cart:cart-list"), {"store": str(store.id)}, format="json").data
    client.post(
        reverse("cart:cart-items", kwargs={"pk": cart["id"]}),
        {"variant": str(variant.id), "quantity": 3},
        format="json",
    )
    return cart


def test_cart_money_is_string(auth_client, address, store, company):
    _setup(auth_client, address, store, company)

    response = auth_client.get(reverse("cart:cart-list"))
    payload = _assert_no_floats(response)

    row = payload["results"][0]
    assert MONEY_PATTERN.match(row["subtotal"])
    assert MONEY_PATTERN.match(row["total"])
    assert MONEY_PATTERN.match(row["items"][0]["line_total"])
    assert MONEY_PATTERN.match(row["items"][0]["variant"]["price"])


def test_checkout_money_is_string(auth_client, address, store, company):
    _setup(auth_client, address, store, company)

    response = auth_client.post(
        reverse("orders:checkout"),
        {"address_id": str(address.id), "store_ids": [str(store.id)]},
        format="json",
        HTTP_IDEMPOTENCY_KEY="money-key",
    )
    assert response.status_code == 201, response.data
    payload = _assert_no_floats(response)

    order = payload["orders"][0]
    for field in (
        "subtotal",
        "delivery_fee",
        "discount_total",
        "tax_total",
        "total",
    ):
        assert MONEY_PATTERN.match(order[field]), field

    detail = auth_client.get(reverse("orders:order-detail", kwargs={"pk": order["id"]}))
    detail_payload = json.loads(detail.content)
    item = detail_payload["items"][0]
    assert MONEY_PATTERN.match(item["unit_price"])
    assert MONEY_PATTERN.match(item["line_total"])


def test_preview_money_is_string(auth_client, address, store, company):
    _setup(auth_client, address, store, company)

    response = auth_client.get(reverse("orders:checkout-preview"), {"address_id": str(address.id)})
    payload = _assert_no_floats(response)

    row = payload["stores"][0]
    assert MONEY_PATTERN.match(row["subtotal"])
    assert MONEY_PATTERN.match(row["delivery_fee"])
    assert MONEY_PATTERN.match(row["total"])
