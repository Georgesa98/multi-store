"""Shared fixtures. Tests run against Postgres, like production."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from accounts.models import CustomerProfile
from core.enums import MemberRole, Role
from delivery import services as delivery_services
from stores import services as store_services
from tests.factories import CUSTOMER_PASSWORD, make_courier, zone_for_store

User = get_user_model()


@pytest.fixture(autouse=True)
def _locmem_email(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def customer(db):
    user = User.objects.create_user(
        email="customer@example.com",
        password=CUSTOMER_PASSWORD,
        full_name="Customer One",
        phone="+963900000001",
        role=Role.CUSTOMER,
    )
    CustomerProfile.objects.create(user=user)
    return user


@pytest.fixture
def other_customer(db):
    user = User.objects.create_user(
        email="other@example.com",
        password=CUSTOMER_PASSWORD,
        full_name="Customer Two",
        role=Role.CUSTOMER,
    )
    CustomerProfile.objects.create(user=user)
    return user


@pytest.fixture
def super_admin(db):
    return User.objects.create_superuser(
        email="admin@example.com",
        password=CUSTOMER_PASSWORD,
        full_name="Platform Admin",
    )


def login(api_client, user, password=CUSTOMER_PASSWORD):
    return api_client.post(
        "/api/v1/auth/login/",
        {"email": user.email, "password": password},
        format="json",
    )


def client_for(user) -> APIClient:
    client = APIClient()
    response = login(client, user)
    assert response.status_code == 200, response.data
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
    return client


@pytest.fixture
def auth_client(customer):
    return client_for(customer)


@pytest.fixture
def make_store(db):
    """Create an approved store with a password-carrying owner."""

    def _make(slug="pizza-place", name="Pizza Place", email="owner@pizza.test"):
        store = store_services.create_store_with_owner(
            name=name,
            slug=slug,
            owner_email=email,
            owner_full_name=f"{name} Owner",
        )
        store.owner.set_password(CUSTOMER_PASSWORD)
        store.owner.save(update_fields=["password"])
        store_services.approve_store(store)
        store.refresh_from_db()
        return store

    return _make


@pytest.fixture
def store(make_store):
    return make_store()


@pytest.fixture
def other_store(make_store):
    return make_store(slug="burger-barn", name="Burger Barn", email="owner@burger.test")


@pytest.fixture
def dashboard_client(store):
    return client_for(store.owner)


@pytest.fixture
def other_dashboard_client(other_store):
    return client_for(other_store.owner)


@pytest.fixture
def staff_client(store):
    user = User.objects.create_user(
        email="staff@pizza.test",
        password=CUSTOMER_PASSWORD,
        full_name="Pizza Staff",
        role=Role.STORE_STAFF,
    )
    from stores.models import StoreMembership

    StoreMembership.objects.create(store=store, user=user, role=MemberRole.STAFF)
    return client_for(user)


@pytest.fixture
def platform_client(super_admin):
    return client_for(super_admin)


@pytest.fixture
def make_company(db):
    """Create an approved delivery company with a password-carrying owner."""

    def _make(slug="fast-lane", name="Fast Lane Delivery", email="delivery@fastlane.test"):
        company = delivery_services.create_company_with_owner(
            name=name,
            slug=slug,
            owner_email=email,
            owner_full_name=f"{name} Owner",
        )
        company.owner.set_password(CUSTOMER_PASSWORD)
        company.owner.save(update_fields=["password"])
        delivery_services.approve_company(company)
        company.refresh_from_db()
        return company

    return _make


@pytest.fixture
def company(make_company):
    return make_company()


@pytest.fixture
def other_company(make_company):
    return make_company(slug="swift-riders", name="Swift Riders", email="delivery@swift.test")


@pytest.fixture
def company_client(company):
    return client_for(company.owner)


@pytest.fixture
def other_company_client(other_company):
    return client_for(other_company.owner)


@pytest.fixture
def courier(company):
    return make_courier(company).user


@pytest.fixture
def courier_client(courier):
    return client_for(courier)


@pytest.fixture
def second_courier(company):
    return make_courier(
        company,
        email="courier.two@pizza.test",
        full_name="Courier Two",
        phone="+963900000004",
    ).user


@pytest.fixture
def make_customer(db):
    def _make(email="shopper@example.com", full_name="Shopper"):
        user = User.objects.create_user(
            email=email,
            password=CUSTOMER_PASSWORD,
            full_name=full_name,
            role=Role.CUSTOMER,
        )
        CustomerProfile.objects.create(user=user)
        return user

    return _make


@pytest.fixture
def address(customer):
    from accounts.models import Address

    return Address.objects.create(
        customer=customer,
        label="Home",
        line1="1 Straight Street",
        city="Damascus",
        lat=Decimal("33.510000"),
        lng=Decimal("36.290000"),
        is_default=True,
    )


@pytest.fixture
def zone(company, store):
    return zone_for_store(store, company)
