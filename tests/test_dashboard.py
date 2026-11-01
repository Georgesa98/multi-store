"""Dashboard CRUD — the store's own catalogue, hours, zones and couriers."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from catalog.models import InventoryMovement, Product
from core.enums import ProductStatus, StoreStatus
from tests.conftest import client_for

pytestmark = pytest.mark.django_db


class TestStore:
    def test_get_own_store(self, dashboard_client, store):
        response = dashboard_client.get(reverse("dashboard:store"))

        assert response.status_code == 200
        assert response.data["slug"] == store.slug
        assert response.data["status"] == StoreStatus.ACTIVE

    def test_patch_own_store(self, dashboard_client, store):
        response = dashboard_client.patch(
            reverse("dashboard:store"),
            {"name": "Pizza Place 2", "is_accepting_orders": False},
            format="json",
        )

        assert response.status_code == 200
        store.refresh_from_db()
        assert store.name == "Pizza Place 2"
        assert store.is_accepting_orders is False

    def test_status_is_not_self_editable(self, dashboard_client, store):
        response = dashboard_client.patch(
            reverse("dashboard:store"),
            {"status": StoreStatus.ACTIVE, "commission_rate": "0.0000"},
            format="json",
        )

        assert response.status_code == 200
        store.refresh_from_db()
        assert store.commission_rate != 0

    def test_owner_can_log_in_and_is_store_admin(self, store):
        client = client_for(store.owner)
        response = client.get(reverse("dashboard:store"))
        assert response.status_code == 200


class TestOpeningHours:
    def test_bulk_replace(self, dashboard_client):
        rows = [
            {
                "weekday": day,
                "open_time": "09:00",
                "close_time": "22:00",
                "is_closed": day == 6,
            }
            for day in range(7)
        ]

        response = dashboard_client.put(
            reverse("dashboard:opening-hours"), {"hours": rows}, format="json"
        )

        assert response.status_code == 200, response.data
        assert len(response.data) == 7

        replaced = dashboard_client.put(
            reverse("dashboard:opening-hours"),
            {"hours": rows[:3]},
            format="json",
        )
        assert replaced.status_code == 200
        assert dashboard_client.get(reverse("dashboard:opening-hours")).data == replaced.data

    def test_duplicate_weekday_is_rejected(self, dashboard_client):
        row = {"weekday": 1, "open_time": "09:00", "close_time": "22:00"}
        response = dashboard_client.put(
            reverse("dashboard:opening-hours"),
            {"hours": [row, row]},
            format="json",
        )
        assert response.status_code == 400

    def test_close_before_open_is_rejected(self, dashboard_client):
        response = dashboard_client.put(
            reverse("dashboard:opening-hours"),
            {"hours": [{"weekday": 1, "open_time": "22:00", "close_time": "09:00"}]},
            format="json",
        )
        assert response.status_code == 400


class TestZones:
    def test_create_list_patch_and_soft_delete(self, dashboard_client):
        payload = {
            "name": "Downtown",
            "center_lat": "33.510000",
            "center_lng": "36.290000",
            "radius_km": "5.00",
            "fee": "5000.00",
            "min_order_total": "25000.00",
            "eta_minutes": 30,
        }
        created = dashboard_client.post(reverse("dashboard:zone-list"), payload, format="json")
        assert created.status_code == 201, created.data
        assert created.data["fee"] == "5000.00"  # money is a string
        zone_id = created.data["id"]

        listed = dashboard_client.get(reverse("dashboard:zone-list"))
        assert listed.data["count"] == 1

        patched = dashboard_client.patch(
            reverse("dashboard:zone-detail", kwargs={"pk": zone_id}),
            {"fee": "6000.00"},
            format="json",
        )
        assert patched.status_code == 200
        assert patched.data["fee"] == "6000.00"

        deleted = dashboard_client.delete(reverse("dashboard:zone-detail", kwargs={"pk": zone_id}))
        assert deleted.status_code == 204
        still_there = dashboard_client.get(reverse("dashboard:zone-detail", kwargs={"pk": zone_id}))
        assert still_there.data["is_active"] is False


class TestCategories:
    def test_create_and_archive(self, dashboard_client):
        created = dashboard_client.post(
            reverse("dashboard:category-list"),
            {"name": "Pizza", "sort_order": 1},
            format="json",
        )
        assert created.status_code == 201, created.data
        assert created.data["slug"] == "pizza"

        deleted = dashboard_client.delete(
            reverse("dashboard:category-detail", kwargs={"pk": created.data["id"]})
        )
        assert deleted.status_code == 204

        detail = dashboard_client.get(
            reverse("dashboard:category-detail", kwargs={"pk": created.data["id"]})
        )
        assert detail.data["is_active"] is False


class TestProducts:
    def test_create_with_default_variant_and_initial_stock(self, dashboard_client, store):
        response = dashboard_client.post(
            reverse("dashboard:product-list"),
            {"name": "Margherita", "price": "12000.00", "stock_qty": 5},
            format="json",
        )

        assert response.status_code == 201, response.data
        assert response.data["slug"] == "margherita"
        assert response.data["status"] == ProductStatus.DRAFT
        variant = response.data["variants"][0]
        assert variant["label"] == "Default"
        assert variant["price"] == "12000.00"
        assert variant["stock_qty"] == 5

        product = Product.objects.get(pk=response.data["id"])
        movement = InventoryMovement.objects.get(variant__product=product)
        assert movement.delta == 5
        assert movement.reason == "restock"

    def test_create_without_price_has_no_variant(self, dashboard_client):
        response = dashboard_client.post(
            reverse("dashboard:product-list"), {"name": "Cola"}, format="json"
        )
        assert response.status_code == 201
        assert response.data["variants"] == []

    def test_foreign_category_is_rejected(self, dashboard_client, other_store):
        foreign = other_store.categories.create(name="Burgers", slug="burgers")
        response = dashboard_client.post(
            reverse("dashboard:product-list"),
            {"name": "Margherita", "category": str(foreign.id)},
            format="json",
        )
        assert response.status_code == 400
        assert "category" in response.data

    def test_list_filters(self, dashboard_client):
        dashboard_client.post(
            reverse("dashboard:product-list"),
            {"name": "Margherita", "status": "active"},
            format="json",
        )
        dashboard_client.post(reverse("dashboard:product-list"), {"name": "Cola"}, format="json")

        assert dashboard_client.get(reverse("dashboard:product-list")).data["count"] == 2
        active = dashboard_client.get(reverse("dashboard:product-list"), {"status": "active"})
        assert active.data["count"] == 1
        searched = dashboard_client.get(reverse("dashboard:product-list"), {"q": "cola"})
        assert searched.data["count"] == 1

    def test_delete_archives_instead_of_deleting(self, dashboard_client):
        created = dashboard_client.post(
            reverse("dashboard:product-list"), {"name": "Margherita"}, format="json"
        )
        assert created.status_code == 201
        product_id = created.data["id"]

        response = dashboard_client.delete(
            reverse("dashboard:product-detail", kwargs={"pk": product_id})
        )

        assert response.status_code == 200
        assert response.data["status"] == ProductStatus.ARCHIVED
        assert Product.objects.filter(pk=product_id).exists()


class TestVariantsAndStock:
    def _product(self, dashboard_client):
        return dashboard_client.post(
            reverse("dashboard:product-list"),
            {"name": "Margherita", "price": "12000.00", "stock_qty": 2},
            format="json",
        ).data

    def test_add_variant(self, dashboard_client):
        product = self._product(dashboard_client)

        response = dashboard_client.post(
            reverse("dashboard:product-variants", kwargs={"pk": product["id"]}),
            {"label": "Large", "price": "16000.00", "stock_qty": 3},
            format="json",
        )

        assert response.status_code == 201, response.data
        assert response.data["label"] == "Large"
        assert response.data["stock_qty"] == 3

        duplicate = dashboard_client.post(
            reverse("dashboard:product-variants", kwargs={"pk": product["id"]}),
            {"label": "Large", "price": "1.00"},
            format="json",
        )
        assert duplicate.status_code == 409

    def test_stock_adjustment_writes_movements(self, dashboard_client):
        product = self._product(dashboard_client)
        variant_id = product["variants"][0]["id"]

        restock = dashboard_client.post(
            reverse("dashboard:variant-stock", kwargs={"pk": variant_id}),
            {"delta": 10, "reason": "restock", "note": "delivery"},
            format="json",
        )
        assert restock.status_code == 201, restock.data
        assert restock.data["variant"]["stock_qty"] == 12

        damage = dashboard_client.post(
            reverse("dashboard:variant-stock", kwargs={"pk": variant_id}),
            {"delta": -2, "reason": "damage"},
            format="json",
        )
        assert damage.status_code == 201
        assert damage.data["variant"]["stock_qty"] == 10

        movements = dashboard_client.get(reverse("dashboard:inventory-movements"))
        assert movements.data["count"] == 3  # initial + restock + damage

    def test_cannot_drop_below_zero(self, dashboard_client):
        variant_id = self._product(dashboard_client)["variants"][0]["id"]

        response = dashboard_client.post(
            reverse("dashboard:variant-stock", kwargs={"pk": variant_id}),
            {"delta": -99, "reason": "manual"},
            format="json",
        )

        assert response.status_code == 422

    def test_order_only_reasons_are_rejected(self, dashboard_client):
        variant_id = self._product(dashboard_client)["variants"][0]["id"]

        response = dashboard_client.post(
            reverse("dashboard:variant-stock", kwargs={"pk": variant_id}),
            {"delta": 1, "reason": "sale"},
            format="json",
        )

        assert response.status_code == 400

    def test_price_update_does_not_touch_stock(self, dashboard_client):
        product = self._product(dashboard_client)
        variant_id = product["variants"][0]["id"]

        response = dashboard_client.patch(
            reverse("dashboard:variant-detail", kwargs={"pk": variant_id}),
            {"price": "13000.00"},
            format="json",
        )

        assert response.status_code == 200
        assert response.data["price"] == "13000.00"
        assert response.data["stock_qty"] == 2


class TestImages:
    def test_upload_image(self, dashboard_client, settings, tmp_path):
        settings.MEDIA_ROOT = tmp_path
        from io import BytesIO

        from PIL import Image

        buffer = BytesIO()
        Image.new("RGB", (8, 8), "red").save(buffer, "PNG")
        upload = SimpleUploadedFile("pizza.png", buffer.getvalue(), content_type="image/png")

        created = dashboard_client.post(
            reverse("dashboard:product-list"), {"name": "Margherita"}, format="json"
        )

        response = dashboard_client.post(
            reverse("dashboard:product-images", kwargs={"pk": created.data["id"]}),
            {"image": upload, "alt": "Our pizza"},
            format="multipart",
        )

        assert response.status_code == 201, response.data
        assert response.data["alt"] == "Our pizza"


class TestCouriers:
    def test_invite_list_and_deactivate(self, dashboard_client, store):
        invited = dashboard_client.post(
            reverse("dashboard:courier-invite"),
            {"email": "courier@pizza.test", "full_name": "Courier One"},
            format="json",
        )

        assert invited.status_code == 201, invited.data
        assert invited.data["user"]["email"] == "courier@pizza.test"

        listed = dashboard_client.get(reverse("dashboard:courier-list"))
        assert listed.data["count"] == 1

        deactivated = dashboard_client.patch(
            reverse("dashboard:courier-detail", kwargs={"pk": invited.data["id"]}),
            {"is_active": False},
            format="json",
        )
        assert deactivated.status_code == 200

        from accounts.models import CourierProfile

        profile = CourierProfile.objects.get(pk=invited.data["id"])
        assert profile.user.is_active is False
