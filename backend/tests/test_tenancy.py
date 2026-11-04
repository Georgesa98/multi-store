"""Tenancy guardrails.

Two stores, one fixture each: a store admin touching another store's object
must get 404, never 403, so object existence never leaks. Written before the
rest of the dashboard API, per section 12.
"""

import pytest
from django.urls import reverse

from catalog import services as catalog_services
from core.enums import Role
from core.tenancy import resolve_company_id, resolve_store_id
from delivery.models import DeliveryZone
from tests.conftest import CUSTOMER_PASSWORD, client_for

pytestmark = pytest.mark.django_db


def _product(store, name="Margherita"):
    product, _ = catalog_services.create_product(store=store, name=name, price="1000.00")
    return product


def test_customer_has_no_store(db, customer):
    assert resolve_store_id(customer) is None


def test_courier_resolves_to_their_company(courier, company):
    assert resolve_company_id(courier) == company.id
    assert resolve_store_id(courier) is None


def test_super_admin_has_no_store_but_is_unscoped(db, super_admin):
    assert resolve_store_id(super_admin) is None
    assert super_admin.role == Role.SUPER_ADMIN


def test_anonymous_user_has_no_store():
    from django.contrib.auth.models import AnonymousUser

    assert resolve_store_id(AnonymousUser()) is None


def test_cross_tenant_product_detail_is_404(other_dashboard_client, other_store, store):
    foreign = _product(store)

    response = other_dashboard_client.get(
        reverse("dashboard:product-detail", kwargs={"pk": foreign.id})
    )
    assert response.status_code == 404


def test_cross_tenant_product_patch_is_404(other_dashboard_client, other_store, store):
    foreign = _product(store)

    response = other_dashboard_client.patch(
        reverse("dashboard:product-detail", kwargs={"pk": foreign.id}),
        {"name": "Hijacked"},
        format="json",
    )
    assert response.status_code == 404


def test_cross_tenant_product_delete_is_404(other_dashboard_client, other_store, store):
    foreign = _product(store)

    response = other_dashboard_client.delete(
        reverse("dashboard:product-detail", kwargs={"pk": foreign.id})
    )
    assert response.status_code == 404


def test_cross_tenant_variant_stock_is_404(other_dashboard_client, other_store, store):
    product = _product(store)
    variant = product.variants.first()

    response = other_dashboard_client.post(
        reverse("dashboard:variant-stock", kwargs={"pk": variant.id}),
        {"delta": 10, "reason": "restock"},
        format="json",
    )
    assert response.status_code == 404


def test_cross_tenant_variant_patch_is_404(other_dashboard_client, other_store, store):
    variant = _product(store).variants.first()

    response = other_dashboard_client.patch(
        reverse("dashboard:variant-detail", kwargs={"pk": variant.id}),
        {"price": "1.00"},
        format="json",
    )
    assert response.status_code == 404


def test_cross_company_zone_is_404(other_company_client, company):
    foreign_zone = DeliveryZone.objects.create(
        company=company,
        name="Downtown",
        center_lat="33.510000",
        center_lng="36.290000",
        radius_km="5.00",
        fee="5000.00",
        min_order_total="0.00",
        eta_minutes=30,
    )

    response = other_company_client.patch(
        reverse("company:zone-detail", kwargs={"pk": foreign_zone.id}),
        {"name": "Hijacked"},
        format="json",
    )
    assert response.status_code == 404


def test_cross_tenant_category_is_404(other_dashboard_client, other_store, store):
    category = store.categories.create(name="Pizza", slug="pizza")

    response = other_dashboard_client.delete(
        reverse("dashboard:category-detail", kwargs={"pk": category.id})
    )
    assert response.status_code == 404


def test_cross_company_courier_is_404(other_company_client, company, courier):
    """A courier belongs to a company; another company never sees them."""
    response = other_company_client.patch(
        reverse("company:courier-detail", kwargs={"pk": courier.courier_profile.id}),
        {"is_active": False},
        format="json",
    )
    assert response.status_code == 404


def test_cross_tenant_inventory_movements_are_not_visible(
    other_dashboard_client, other_store, store
):
    product = _product(store)
    catalog_services.adjust_stock(variant=product.variants.first(), delta=5, reason="restock")

    response = other_dashboard_client.get(reverse("dashboard:inventory-movements"))

    assert response.status_code == 200
    assert response.data["count"] == 0


def test_store_admin_without_membership_gets_403(db):
    from django.contrib.auth import get_user_model

    from stores.models import Store

    User = get_user_model()
    orphan = User.objects.create_user(
        email="orphan@example.com",
        password=CUSTOMER_PASSWORD,
        full_name="Orphan Admin",
        role=Role.STORE_ADMIN,
    )
    Store.objects.create(owner=orphan, slug="orphan-store", name="Orphan Store")

    client = client_for(orphan)
    response = client.get(reverse("dashboard:store"))

    assert response.status_code == 403


def test_staff_is_read_only(staff_client, store):
    response = staff_client.get(reverse("dashboard:store"))
    assert response.status_code == 200

    write = staff_client.patch(reverse("dashboard:store"), {"name": "Renamed"}, format="json")
    assert write.status_code == 403


def test_customer_cannot_reach_dashboard(auth_client):
    response = auth_client.get(reverse("dashboard:store"))
    assert response.status_code == 403


def _order(store, customer, suffix=1):
    from decimal import Decimal

    from orders.models import CheckoutGroup, Order

    group = CheckoutGroup.objects.create(customer=customer, address_snapshot={})
    return Order.objects.create(
        store=store,
        group=group,
        customer=customer,
        number=f"{store.code}-{suffix:06d}",
        subtotal=Decimal("1000.00"),
        total=Decimal("1000.00"),
    )


def test_cross_tenant_order_detail_is_404(other_dashboard_client, other_store, store, customer):
    order = _order(store, customer)

    response = other_dashboard_client.get(
        reverse("dashboard:order-detail", kwargs={"pk": order.id})
    )

    assert response.status_code == 404


def test_cross_tenant_order_list_excludes_foreign_orders(
    other_dashboard_client, other_store, store, customer
):
    _order(store, customer)

    response = other_dashboard_client.get(reverse("dashboard:order-list"))

    assert response.status_code == 200
    assert response.data["results"] == []


def test_customer_sees_only_their_own_orders(auth_client, customer, store, make_customer):
    mine = _order(store, customer, suffix=1)
    theirs = _order(store, make_customer(email="stranger@example.com"), suffix=2)

    listed = auth_client.get(reverse("orders:order-list"))
    assert [row["id"] for row in listed.data["results"]] == [str(mine.id)]

    detail = auth_client.get(reverse("orders:order-detail", kwargs={"pk": theirs.id}))
    assert detail.status_code == 404


def test_customer_cannot_read_another_customers_address(auth_client, make_customer):
    from accounts.models import Address

    stranger = make_customer(email="stranger@example.com")
    foreign = Address.objects.create(customer=stranger, line1="X", city="Damascus")

    response = auth_client.get(reverse("addresses:address-detail", kwargs={"pk": foreign.id}))

    assert response.status_code == 404
