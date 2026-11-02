"""Reviews: one per delivered item, counters refreshed, store-scoped replies."""

from decimal import Decimal

import pytest
from django.urls import reverse

from accounts.models import Address
from catalog import services as catalog_services
from core.enums import ProductStatus
from delivery import services as delivery_services
from delivery.models import Delivery
from orders.models import Order
from reviews.models import Review
from tests.conftest import client_for

pytestmark = pytest.mark.django_db


def _product(store, name="Margherita", price="12000.00"):
    product, variant = catalog_services.create_product(
        store=store,
        name=name,
        price=price,
        stock_qty=10,
        status=ProductStatus.ACTIVE,
    )
    return product, variant


def _checkout(client, address, store, variant, key):
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
            reverse(f"dashboard:order-{step}", kwargs={"pk": order.id}), format="json"
        )
        assert response.status_code == 200, (step, response.data)
    order.refresh_from_db()
    return order


def _deliver(auth_client, dashboard_client, address, store, company, courier, variant, key):
    order = _checkout(auth_client, address, store, variant, key)
    _advance(dashboard_client, order, "confirm", "preparing", "ready")
    delivery = Delivery.objects.get(order=order)
    delivery_services.assign_courier(delivery, courier=courier, actor=company.owner)
    delivery_services.pickup(delivery, courier=courier)
    delivery_services.deliver(delivery, courier=courier)
    order.refresh_from_db()
    assert order.status == "delivered"
    return order


@pytest.fixture
def delivered(auth_client, dashboard_client, address, store, company, zone, courier):
    product, variant = _product(store)
    order = _deliver(
        auth_client,
        dashboard_client,
        address,
        store,
        company,
        courier,
        variant,
        "review-delivered",
    )
    return {"order": order, "product": product, "item": order.items.get()}


class TestPostReview:
    def test_reviewing_a_delivered_item_updates_the_product(self, delivered, auth_client):
        item = delivered["item"]

        response = auth_client.post(
            reverse("orders:order-item-review", kwargs={"pk": item.id}),
            {"rating": 5, "comment": "Arrived hot."},
            format="json",
        )

        assert response.status_code == 201, response.data
        assert response.data["rating"] == 5
        assert response.data["comment"] == "Arrived hot."

        review = Review.objects.get(order_item=item)
        assert review.customer_id == delivered["order"].customer_id
        assert review.store_id == delivered["order"].store_id

        product = delivered["product"]
        product.refresh_from_db()
        assert product.avg_rating == Decimal("5.00")
        assert product.rating_count == 1

    def test_a_pending_order_cannot_be_reviewed(self, auth_client, address, store, company, zone):
        _, variant = _product(store)
        order = _checkout(auth_client, address, store, variant, "review-pending")

        response = auth_client.post(
            reverse("orders:order-item-review", kwargs={"pk": order.items.get().id}),
            {"rating": 4},
            format="json",
        )

        assert response.status_code == 422
        assert Review.objects.count() == 0

    def test_another_customers_item_is_404(self, delivered, other_customer):
        response = client_for(other_customer).post(
            reverse("orders:order-item-review", kwargs={"pk": delivered["item"].id}),
            {"rating": 1},
            format="json",
        )
        assert response.status_code == 404

    def test_one_review_per_item(self, delivered, auth_client):
        url = reverse("orders:order-item-review", kwargs={"pk": delivered["item"].id})
        assert auth_client.post(url, {"rating": 4}, format="json").status_code == 201

        again = auth_client.post(url, {"rating": 2}, format="json")

        assert again.status_code == 409
        assert Review.objects.filter(order_item=delivered["item"]).count() == 1

    def test_rating_must_be_between_one_and_five(self, delivered, auth_client):
        url = reverse("orders:order-item-review", kwargs={"pk": delivered["item"].id})

        assert auth_client.post(url, {"rating": 0}, format="json").status_code == 400
        assert auth_client.post(url, {"rating": 6}, format="json").status_code == 400

    def test_average_rating_spans_customers(
        self,
        delivered,
        auth_client,
        other_customer,
        dashboard_client,
        store,
        company,
        courier,
        address,
        zone,
    ):
        product = delivered["product"]
        auth_client.post(
            reverse("orders:order-item-review", kwargs={"pk": delivered["item"].id}),
            {"rating": 5},
            format="json",
        )

        other_address = Address.objects.create(
            customer=other_customer,
            label="Work",
            line1="2 Straight Street",
            city="Damascus",
            lat=address.lat,
            lng=address.lng,
            is_default=True,
        )
        other_client = client_for(other_customer)
        second_order = _deliver(
            other_client,
            dashboard_client,
            other_address,
            store,
            company,
            courier,
            product.variants.get(),
            "review-second",
        )
        other_client.post(
            reverse("orders:order-item-review", kwargs={"pk": second_order.items.get().id}),
            {"rating": 3},
            format="json",
        )

        product.refresh_from_db()
        assert product.rating_count == 2
        assert product.avg_rating == Decimal("4.00")


class TestDashboardReviews:
    def test_reply_is_stored_and_stamped(self, delivered, dashboard_client):
        review = Review.objects.create(
            order_item=delivered["item"],
            customer=delivered["order"].customer,
            store=delivered["order"].store,
            product=delivered["product"],
            rating=4,
            comment="Good",
        )

        response = dashboard_client.post(
            reverse("dashboard:review-reply", kwargs={"pk": review.id}),
            {"reply": "Thank you!"},
            format="json",
        )

        assert response.status_code == 200, response.data
        assert response.data["store_reply"] == "Thank you!"
        review.refresh_from_db()
        assert review.replied_at is not None

    def test_list_and_reply_are_store_scoped(
        self, delivered, dashboard_client, other_dashboard_client
    ):
        review = Review.objects.create(
            order_item=delivered["item"],
            customer=delivered["order"].customer,
            store=delivered["order"].store,
            product=delivered["product"],
            rating=4,
        )

        mine = dashboard_client.get(reverse("dashboard:review-list"))
        assert mine.data["count"] == 1

        theirs = other_dashboard_client.get(reverse("dashboard:review-list"))
        assert theirs.data["count"] == 0

        reply = other_dashboard_client.post(
            reverse("dashboard:review-reply", kwargs={"pk": review.id}),
            {"reply": "Not mine"},
            format="json",
        )
        assert reply.status_code == 404

    def test_staff_may_read_but_not_reply(self, delivered, staff_client):
        review = Review.objects.create(
            order_item=delivered["item"],
            customer=delivered["order"].customer,
            store=delivered["order"].store,
            product=delivered["product"],
            rating=4,
        )

        assert staff_client.get(reverse("dashboard:review-list")).status_code == 200
        response = staff_client.post(
            reverse("dashboard:review-reply", kwargs={"pk": review.id}),
            {"reply": "Hi"},
            format="json",
        )
        assert response.status_code == 403


class TestPublicReviews:
    def test_reviews_are_public_and_scoped_to_the_store(
        self, delivered, api_client, store, other_store
    ):
        Review.objects.create(
            order_item=delivered["item"],
            customer=delivered["order"].customer,
            store=store,
            product=delivered["product"],
            rating=5,
            comment="Excellent",
        )

        response = api_client.get(reverse("public:store-review-list", kwargs={"slug": store.slug}))

        assert response.status_code == 200
        assert response.data["count"] == 1
        assert response.data["results"][0]["comment"] == "Excellent"

        other = api_client.get(
            reverse("public:store-review-list", kwargs={"slug": other_store.slug})
        )
        assert other.data["count"] == 0

    def test_unknown_store_is_404(self, api_client):
        response = api_client.get(
            reverse("public:store-review-list", kwargs={"slug": "no-such-store"})
        )
        assert response.status_code == 404
