"""Phase 0 — authentication, profile and device tokens."""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from accounts.models import CustomerProfile
from core.enums import Role
from tests.conftest import CUSTOMER_PASSWORD

User = get_user_model()

pytestmark = pytest.mark.django_db


class TestRegister:
    def test_customer_signup_returns_tokens_and_profile(self, api_client):
        response = api_client.post(
            reverse("auth:register"),
            {
                "email": "new@example.com",
                "full_name": "New Customer",
                "phone": "+963900000009",
                "password": "Str0ngPass!23",
            },
            format="json",
        )

        assert response.status_code == 201, response.data
        assert response.data["role"] == Role.CUSTOMER
        assert {"access", "refresh", "user"} <= set(response.data)

        user = User.objects.get(email="new@example.com")
        assert user.role == Role.CUSTOMER
        assert user.check_password("Str0ngPass!23")
        assert CustomerProfile.objects.filter(user=user).exists()

    def test_duplicate_email_is_rejected_case_insensitively(self, api_client, customer):
        response = api_client.post(
            reverse("auth:register"),
            {
                "email": "CUSTOMER@example.com",
                "full_name": "Clone",
                "password": "Str0ngPass!23",
            },
            format="json",
        )

        assert response.status_code == 400
        assert "email" in response.data

    def test_weak_password_is_rejected_by_django_validators(self, api_client):
        response = api_client.post(
            reverse("auth:register"),
            {"email": "weak@example.com", "full_name": "Weak", "password": "12345678"},
            format="json",
        )

        assert response.status_code == 400
        assert "password" in response.data


class TestLoginLogout:
    def test_login_returns_role_and_user(self, api_client, customer):
        response = api_client.post(
            reverse("auth:login"),
            {"email": customer.email, "password": CUSTOMER_PASSWORD},
            format="json",
        )

        assert response.status_code == 200
        assert response.data["role"] == Role.CUSTOMER
        assert response.data["user"]["id"] == str(customer.id)

    def test_wrong_password_is_rejected(self, api_client, customer):
        response = api_client.post(
            reverse("auth:login"),
            {"email": customer.email, "password": "wrong-password"},
            format="json",
        )

        assert response.status_code in (401, 400)

    def test_inactive_user_cannot_log_in(self, api_client, customer):
        customer.is_active = False
        customer.save(update_fields=["is_active"])

        response = api_client.post(
            reverse("auth:login"),
            {"email": customer.email, "password": CUSTOMER_PASSWORD},
            format="json",
        )

        assert response.status_code in (401, 400)

    def test_refresh_rotates_and_old_refresh_is_blacklisted(self, api_client, customer):
        login = api_client.post(
            reverse("auth:login"),
            {"email": customer.email, "password": CUSTOMER_PASSWORD},
            format="json",
        )
        old_refresh = login.data["refresh"]

        first = api_client.post(reverse("auth:refresh"), {"refresh": old_refresh}, format="json")
        assert first.status_code == 200
        assert first.data["refresh"] != old_refresh

        replay = api_client.post(reverse("auth:refresh"), {"refresh": old_refresh}, format="json")
        assert replay.status_code == 401

    def test_logout_blacklists_refresh(self, api_client, customer):
        login = api_client.post(
            reverse("auth:login"),
            {"email": customer.email, "password": CUSTOMER_PASSWORD},
            format="json",
        )
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

        response = api_client.post(
            reverse("auth:logout"), {"refresh": login.data["refresh"]}, format="json"
        )
        assert response.status_code == 204

        reuse = api_client.post(
            reverse("auth:refresh"), {"refresh": login.data["refresh"]}, format="json"
        )
        assert reuse.status_code == 401


class TestLoginLockout:
    def test_repeated_failures_lock_the_address(self, api_client, customer, settings):
        settings.LOGIN_LOCKOUT_THRESHOLD = 3
        wrong = {"email": customer.email, "password": "wrong-password"}

        for _ in range(3):
            assert api_client.post(reverse("auth:login"), wrong, format="json").status_code == 401

        locked = api_client.post(reverse("auth:login"), wrong, format="json")

        assert locked.status_code == 429
        assert locked.data["code"] == "account_locked"
        assert int(locked["Retry-After"]) > 0

    def test_the_right_password_is_refused_while_locked(self, api_client, customer, settings):
        settings.LOGIN_LOCKOUT_THRESHOLD = 2
        wrong = {"email": customer.email, "password": "wrong-password"}
        for _ in range(2):
            api_client.post(reverse("auth:login"), wrong, format="json")

        right = api_client.post(
            reverse("auth:login"),
            {"email": customer.email, "password": CUSTOMER_PASSWORD},
            format="json",
        )

        assert right.status_code == 429
        assert right.data["code"] == "account_locked"

    def test_a_success_resets_the_counter(self, api_client, customer, settings):
        settings.LOGIN_LOCKOUT_THRESHOLD = 3
        wrong = {"email": customer.email, "password": "wrong-password"}
        for _ in range(2):
            api_client.post(reverse("auth:login"), wrong, format="json")

        good = api_client.post(
            reverse("auth:login"),
            {"email": customer.email, "password": CUSTOMER_PASSWORD},
            format="json",
        )
        assert good.status_code == 200

        for _ in range(2):
            assert api_client.post(reverse("auth:login"), wrong, format="json").status_code == 401

        still_allowed = api_client.post(
            reverse("auth:login"),
            {"email": customer.email, "password": CUSTOMER_PASSWORD},
            format="json",
        )
        assert still_allowed.status_code == 200

    def test_a_locked_address_does_not_reveal_whether_it_exists(self, api_client, settings):
        settings.LOGIN_LOCKOUT_THRESHOLD = 2
        ghost = {"email": "ghost@example.com", "password": "wrong-password"}
        for _ in range(2):
            api_client.post(reverse("auth:login"), ghost, format="json")

        response = api_client.post(reverse("auth:login"), ghost, format="json")

        assert response.status_code == 429
        assert response.data["code"] == "account_locked"


class TestMe:
    def test_requires_authentication(self, api_client):
        assert api_client.get(reverse("auth:me")).status_code == 401

    def test_returns_current_user(self, auth_client, customer):
        response = auth_client.get(reverse("auth:me"))

        assert response.status_code == 200
        assert response.data["email"] == customer.email
        assert response.data["role"] == Role.CUSTOMER

    def test_patch_updates_allowed_fields_only(self, auth_client):
        response = auth_client.patch(
            reverse("auth:me"), {"full_name": "Renamed", "role": "super_admin"}, format="json"
        )

        assert response.status_code == 200
        assert response.data["full_name"] == "Renamed"
        assert response.data["role"] == Role.CUSTOMER


class TestPassword:
    def test_change_password_requires_correct_old_password(self, auth_client):
        response = auth_client.post(
            reverse("auth:password-change"),
            {"old_password": "nope", "new_password": "N3wStr0ng!23"},
            format="json",
        )
        assert response.status_code == 400
        assert "old_password" in response.data

    def test_change_password_works_and_invalidates_refresh_tokens(self, api_client, customer):
        login = api_client.post(
            reverse("auth:login"),
            {"email": customer.email, "password": CUSTOMER_PASSWORD},
            format="json",
        )
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

        response = api_client.post(
            reverse("auth:password-change"),
            {"old_password": CUSTOMER_PASSWORD, "new_password": "N3wStr0ng!23"},
            format="json",
        )
        assert response.status_code == 204

        customer.refresh_from_db()
        assert customer.check_password("N3wStr0ng!23")

        reuse = api_client.post(
            reverse("auth:refresh"), {"refresh": login.data["refresh"]}, format="json"
        )
        assert reuse.status_code == 401

    def test_reset_request_does_not_leak_account_existence(self, api_client, customer):
        known = api_client.post(
            reverse("auth:password-reset"), {"email": customer.email}, format="json"
        )
        unknown = api_client.post(
            reverse("auth:password-reset"), {"email": "ghost@example.com"}, format="json"
        )

        assert known.status_code == 204
        assert unknown.status_code == 204


class TestDeviceTokens:
    def test_create_list_and_delete(self, auth_client):
        created = auth_client.post(
            reverse("auth:device-token-list"),
            {"token": "fcm-token-1", "platform": "android"},
            format="json",
        )
        assert created.status_code == 201, created.data

        listed = auth_client.get(reverse("auth:device-token-list"))
        assert listed.data["count"] == 1

        deleted = auth_client.delete(
            reverse("auth:device-token-detail", kwargs={"pk": created.data["id"]})
        )
        assert deleted.status_code == 204

    def test_cannot_delete_another_users_token(self, api_client, customer, other_customer):
        from accounts.models import DeviceToken

        foreign = DeviceToken.objects.create(
            user=other_customer, token="foreign-token", platform="ios"
        )
        login = api_client.post(
            reverse("auth:login"),
            {"email": customer.email, "password": CUSTOMER_PASSWORD},
            format="json",
        )
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

        response = api_client.delete(reverse("auth:device-token-detail", kwargs={"pk": foreign.id}))
        assert response.status_code == 404
