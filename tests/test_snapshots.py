"""OrderItem `_snapshot` fields are written once and never follow the product."""

from decimal import Decimal

import pytest
from django.urls import reverse

from catalog import services as catalog_services
from core.enums import ProductStatus
from orders.models import Order, OrderItem
from tests.factories import zone_for_store

pytestmark = pytest.mark.django_db


def test_snapshots_survive_rename_and_reprice(auth_client, address, store, company):
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
    product, variant = catalog_services.create_product(
        store=store,
        name="Margherita",
        price="12000.00",
        stock_qty=5,
        status=ProductStatus.ACTIVE,
    )

    cart = auth_client.post(reverse("cart:cart-list"), {"store": str(store.id)}, format="json").data
    auth_client.post(
        reverse("cart:cart-items", kwargs={"pk": cart["id"]}),
        {"variant": str(variant.id), "quantity": 2},
        format="json",
    )
    response = auth_client.post(
        reverse("orders:checkout"),
        {"address_id": str(address.id), "store_ids": [str(store.id)]},
        format="json",
        HTTP_IDEMPOTENCY_KEY="snapshot-key",
    )
    assert response.status_code == 201, response.data

    item = OrderItem.objects.get(order__group_id=response.data["id"])

    # Rename the product, relabel the variant and reprice it.
    product.name = "Margherita Deluxe"
    product.save(update_fields=["name"])
    variant.label = "Large"
    variant.price = Decimal("99000.00")
    variant.save(update_fields=["label", "price"])

    item.refresh_from_db()
    assert item.name_snapshot == "Margherita"
    assert item.variant_label_snapshot == "Default"
    assert item.unit_price == Decimal("12000.00")
    assert item.line_total == Decimal("24000.00")
    assert item.quantity == 2

    # The order total is not recomputed either.
    order = Order.objects.get(pk=item.order_id)
    assert order.subtotal == Decimal("24000.00")
    assert order.total == Decimal("29000.00")


def test_order_item_model_rejects_update_path(auth_client, address, store, company):
    """Snapshots are plain fields; the API exposes them read-only."""
    zone_for_store(
        store,
        company,
        center_lat="33.510000",
        center_lng="36.290000",
        radius_km="6.00",
        fee="0.00",
        min_order_total="0.00",
        eta_minutes=30,
    )
    _, variant = catalog_services.create_product(
        store=store,
        name="Cola",
        price="3000.00",
        stock_qty=5,
        status=ProductStatus.ACTIVE,
    )
    cart = auth_client.post(reverse("cart:cart-list"), {"store": str(store.id)}, format="json").data
    auth_client.post(
        reverse("cart:cart-items", kwargs={"pk": cart["id"]}),
        {"variant": str(variant.id), "quantity": 1},
        format="json",
    )
    response = auth_client.post(
        reverse("orders:checkout"),
        {"address_id": str(address.id), "store_ids": [str(store.id)]},
        format="json",
        HTTP_IDEMPOTENCY_KEY="readonly-key",
    )

    detail = auth_client.get(
        reverse("orders:order-detail", kwargs={"pk": response.data["orders"][0]["id"]})
    )

    assert detail.status_code == 200
    item_payload = detail.data["items"][0]
    assert "name_snapshot" in item_payload
    assert "unit_price" in item_payload
