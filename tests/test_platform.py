"""Platform (super admin) surface: onboarding, approval, suspension, users."""

import pytest
from django.core import mail
from django.urls import reverse

from core.enums import Role, StoreStatus
from stores.models import Store, StoreMembership

pytestmark = pytest.mark.django_db


class TestStoreOnboarding:
    def test_super_admin_creates_pending_store_with_owner(self, platform_client):
        response = platform_client.post(
            reverse("platform:store-list"),
            {
                "name": "Pizza Place",
                "owner_email": "owner@pizza.test",
                "owner_full_name": "Pizza Owner",
                "description": "Best pizza in town",
            },
            format="json",
        )

        assert response.status_code == 201, response.data
        assert response.data["status"] == StoreStatus.PENDING
        assert response.data["owner_email"] == "owner@pizza.test"

        store = Store.objects.get(slug="pizza-place")
        assert store.owner.role == Role.STORE_ADMIN
        assert store.owner.has_usable_password() is False
        membership = StoreMembership.objects.get(store=store)
        assert membership.user == store.owner
        assert membership.role == "owner"

        assert len(mail.outbox) == 1
        assert "owner@pizza.test" in mail.outbox[0].to

    def test_customer_cannot_onboard(self, auth_client):
        response = auth_client.post(
            reverse("platform:store-list"),
            {"name": "Nope", "owner_email": "x@y.test", "owner_full_name": "X"},
            format="json",
        )
        assert response.status_code == 403

    def test_owner_cannot_manage_a_second_store(self, platform_client, store):
        response = platform_client.post(
            reverse("platform:store-list"),
            {
                "name": "Second",
                "owner_email": store.owner.email,
                "owner_full_name": "Same Owner",
            },
            format="json",
        )
        assert response.status_code == 409

    def test_existing_staff_can_become_store_owner(self, platform_client, staff_client, store):
        from django.contrib.auth import get_user_model

        staff = get_user_model().objects.get(email="staff@pizza.test")
        membership = staff.memberships.first()
        membership.is_active = False
        membership.save(update_fields=["is_active"])

        response = platform_client.post(
            reverse("platform:store-list"),
            {
                "name": "Second",
                "owner_email": staff.email,
                "owner_full_name": staff.full_name,
            },
            format="json",
        )
        assert response.status_code == 201


class TestStoreStatus:
    def test_approve(self, platform_client, store):
        store.status = StoreStatus.PENDING
        store.is_accepting_orders = False
        store.save(update_fields=["status", "is_accepting_orders"])

        response = platform_client.post(reverse("platform:store-approve", kwargs={"pk": store.id}))

        assert response.status_code == 200
        store.refresh_from_db()
        assert store.status == StoreStatus.ACTIVE
        assert store.is_accepting_orders is True

    def test_approving_twice_conflicts(self, platform_client, store):
        response = platform_client.post(reverse("platform:store-approve", kwargs={"pk": store.id}))
        assert response.status_code == 409

    def test_suspend_requires_reason_and_stops_orders(self, platform_client, store):
        missing = platform_client.post(
            reverse("platform:store-suspend", kwargs={"pk": store.id}),
            {},
            format="json",
        )
        assert missing.status_code == 400

        response = platform_client.post(
            reverse("platform:store-suspend", kwargs={"pk": store.id}),
            {"reason": "Repeated complaints"},
            format="json",
        )

        assert response.status_code == 200
        store.refresh_from_db()
        assert store.status == StoreStatus.SUSPENDED
        assert store.is_accepting_orders is False
        assert store.suspended_reason == "Repeated complaints"

    def test_filter_by_status(self, platform_client, store, other_store):
        store.status = StoreStatus.SUSPENDED
        store.save(update_fields=["status"])

        response = platform_client.get(
            reverse("platform:store-list"), {"status": StoreStatus.ACTIVE}
        )

        assert response.data["count"] == 1
        assert response.data["results"][0]["slug"] == other_store.slug


class TestUsers:
    def test_list_and_filter_by_role(self, platform_client, customer, store):
        response = platform_client.get(reverse("platform:user-list"), {"role": Role.CUSTOMER})

        assert response.status_code == 200
        assert response.data["count"] == 1
        assert response.data["results"][0]["email"] == customer.email

    def test_search(self, platform_client, customer):
        response = platform_client.get(reverse("platform:user-list"), {"q": "customer@"})
        assert response.data["count"] == 1

    def test_deactivate_user(self, platform_client, customer):
        response = platform_client.patch(
            reverse("platform:user-detail", kwargs={"pk": customer.id}),
            {"is_active": False},
            format="json",
        )

        assert response.status_code == 200
        customer.refresh_from_db()
        assert customer.is_active is False
