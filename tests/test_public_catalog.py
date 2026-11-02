"""Public store and catalogue browsing, plus delivery quoting."""

import pytest
from django.urls import reverse

from catalog import services as catalog_services
from core.enums import ProductStatus, StoreStatus
from tests.factories import zone_for_store

pytestmark = pytest.mark.django_db


def _active_product(store, name="Margherita", price="12000.00", stock=5):
    product, variant = catalog_services.create_product(
        store=store,
        name=name,
        price=price,
        stock_qty=stock,
        status=ProductStatus.ACTIVE,
    )
    return product, variant


class TestStoreBrowsing:
    def test_only_active_stores_are_listed(self, api_client, store):
        from core.enums import StoreStatus as Status
        from stores.models import Store

        Store.objects.create(
            owner=store.owner,
            slug="pending-store",
            name="Pending Store",
            status=Status.PENDING,
        )

        response = api_client.get(reverse("public:store-list"))

        assert response.status_code == 200
        assert response.data["count"] == 1
        assert response.data["results"][0]["slug"] == store.slug

    def test_search_by_name(self, api_client, store, other_store):
        response = api_client.get(reverse("public:store-list"), {"q": "burger"})

        assert response.data["count"] == 1
        assert response.data["results"][0]["slug"] == other_store.slug

    def test_radius_filter(self, api_client, store):
        store.lat, store.lng = "33.510000", "36.290000"
        store.save(update_fields=["lat", "lng"])

        near = api_client.get(
            reverse("public:store-list"),
            {"lat": "33.511000", "lng": "36.291000", "radius": "2"},
        )
        far = api_client.get(
            reverse("public:store-list"),
            {"lat": "34.730000", "lng": "36.710000", "radius": "2"},
        )

        assert near.data["count"] == 1
        assert far.data["count"] == 0

    def test_detail_includes_hours_and_partners(self, api_client, store, company):
        store.opening_hours.create(weekday=0, open_time="09:00", close_time="22:00")
        zone_for_store(store, company, radius_km="5.00")

        response = api_client.get(reverse("public:store-detail", kwargs={"slug": store.slug}))

        assert response.status_code == 200
        assert len(response.data["opening_hours"]) == 1
        assert response.data["delivery_companies"][0]["name"] == company.name

    def test_suspended_store_is_404(self, api_client, store):
        store.status = StoreStatus.SUSPENDED
        store.save(update_fields=["status"])

        response = api_client.get(reverse("public:store-detail", kwargs={"slug": store.slug}))
        assert response.status_code == 404


class TestCatalogue:
    def test_only_active_available_products_are_listed(self, api_client, store):
        _active_product(store)
        catalog_services.create_product(store=store, name="Draft Pizza")
        catalog_services.create_product(
            store=store, name="Hidden Pizza", status=ProductStatus.ACTIVE, is_available=False
        )

        response = api_client.get(reverse("public:store-product-list", kwargs={"slug": store.slug}))

        assert response.data["count"] == 1
        assert response.data["results"][0]["name"] == "Margherita"

    def test_search_and_category_filters(self, api_client, store):
        category = store.categories.create(name="Pizza", slug="pizza")
        first, _ = _active_product(store, name="Margherita")
        first.category = category
        first.save(update_fields=["category"])
        _active_product(store, name="Cola")

        searched = api_client.get(
            reverse("public:store-product-list", kwargs={"slug": store.slug}),
            {"q": "cola"},
        )
        categorized = api_client.get(
            reverse("public:store-product-list", kwargs={"slug": store.slug}),
            {"category": "pizza"},
        )

        assert searched.data["count"] == 1
        assert categorized.data["count"] == 1
        assert categorized.data["results"][0]["name"] == "Margherita"

    def test_price_and_stock_filters(self, api_client, store):
        _active_product(store, name="Cheap", price="1000.00", stock=3)
        _active_product(store, name="Pricey", price="90000.00", stock=0)

        cheap = api_client.get(
            reverse("public:store-product-list", kwargs={"slug": store.slug}),
            {"max_price": "5000"},
        )
        in_stock = api_client.get(
            reverse("public:store-product-list", kwargs={"slug": store.slug}),
            {"in_stock": "true"},
        )

        assert cheap.data["count"] == 1
        assert in_stock.data["count"] == 1
        assert in_stock.data["results"][0]["name"] == "Cheap"

    def test_product_detail(self, api_client, store):
        product, _ = _active_product(store)

        response = api_client.get(
            reverse(
                "public:store-product-detail",
                kwargs={"store_slug": store.slug, "slug": product.slug},
            )
        )

        assert response.status_code == 200
        assert response.data["price"] == "12000.00"
        assert response.data["in_stock"] is True
        assert len(response.data["variants"]) == 1

    def test_categories_endpoint(self, api_client, store):
        store.categories.create(name="Pizza", slug="pizza")

        response = api_client.get(
            reverse("public:store-category-list", kwargs={"slug": store.slug})
        )

        assert response.status_code == 200
        assert len(response.data) == 1


class TestDeliveryQuote:
    def _zone(self, store, company):
        return zone_for_store(
            store,
            company,
            radius_km="5.00",
            fee="5000.00",
            min_order_total="25000.00",
            eta_minutes=30,
        )

    def test_inside_zone_returns_fee(self, api_client, store, company):
        self._zone(store, company)

        response = api_client.post(
            reverse("public:store-delivery-quote", kwargs={"slug": store.slug}),
            {"lat": "33.512000", "lng": "36.292000"},
            format="json",
        )

        assert response.status_code == 200, response.data
        assert response.data["fee"] == "5000.00"
        assert response.data["min_order_total"] == "25000.00"
        assert response.data["eta_minutes"] == 30

    def test_outside_every_zone_is_422(self, api_client, store, company):
        self._zone(store, company)

        response = api_client.post(
            reverse("public:store-delivery-quote", kwargs={"slug": store.slug}),
            {"lat": "34.730000", "lng": "36.710000"},
            format="json",
        )

        assert response.status_code == 422
