"""Shared fixtures. Tests run against Postgres, like production."""

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from accounts.models import CustomerProfile
from core.enums import Role

User = get_user_model()

CUSTOMER_PASSWORD = "Str0ngPass!23"


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


@pytest.fixture
def auth_client(api_client, customer):
    response = login(api_client, customer)
    assert response.status_code == 200, response.data
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
    return api_client
