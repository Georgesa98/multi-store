"""Delivery companies: platform onboarding, the company dashboard and its team."""

import pytest
from django.core import mail
from django.urls import reverse

from accounts.models import CourierProfile
from core.enums import CompanyStatus, MemberRole, Role
from delivery.models import CompanyMembership, DeliveryCompany, DeliveryZone
from tests.conftest import CUSTOMER_PASSWORD, client_for

pytestmark = pytest.mark.django_db


class TestCompanyOnboarding:
    def test_platform_creates_pending_company_with_owner(self, platform_client):
        response = platform_client.post(
            reverse("platform:company-list"),
            {
                "name": "Fast Lane Delivery",
                "owner_email": "owner@fastlane.test",
                "owner_full_name": "Fast Lane Owner",
                "phone": "+963900000099",
            },
            format="json",
        )

        assert response.status_code == 201, response.data
        assert response.data["status"] == CompanyStatus.PENDING
        assert response.data["slug"] == "fast-lane-delivery"

        company = DeliveryCompany.objects.get(slug="fast-lane-delivery")
        assert company.owner.role == Role.DELIVERY_ADMIN
        assert company.owner.has_usable_password() is False
        membership = CompanyMembership.objects.get(company=company)
        assert membership.user == company.owner
        assert membership.role == MemberRole.OWNER

        assert len(mail.outbox) == 1
        assert "owner@fastlane.test" in mail.outbox[0].to

    def test_customer_cannot_onboard_a_company(self, auth_client):
        response = auth_client.post(
            reverse("platform:company-list"),
            {
                "name": "Nope",
                "owner_email": "x@y.test",
                "owner_full_name": "X",
            },
            format="json",
        )
        assert response.status_code == 403

    def test_one_admin_cannot_own_two_companies(self, platform_client, company):
        response = platform_client.post(
            reverse("platform:company-list"),
            {
                "name": "Second Fleet",
                "owner_email": company.owner.email,
                "owner_full_name": company.owner.full_name,
            },
            format="json",
        )
        assert response.status_code == 409

    def test_store_admin_cannot_be_a_company_owner(self, platform_client, store):
        response = platform_client.post(
            reverse("platform:company-list"),
            {
                "name": "Second Fleet",
                "owner_email": store.owner.email,
                "owner_full_name": store.owner.full_name,
            },
            format="json",
        )
        assert response.status_code == 422


class TestCompanyStatus:
    def test_approve(self, platform_client, company):
        company.status = CompanyStatus.PENDING
        company.is_accepting_jobs = False
        company.save(update_fields=["status", "is_accepting_jobs"])

        response = platform_client.post(
            reverse("platform:company-approve", kwargs={"pk": company.id})
        )

        assert response.status_code == 200
        company.refresh_from_db()
        assert company.status == CompanyStatus.ACTIVE
        assert company.is_accepting_jobs is True

    def test_approving_twice_conflicts(self, platform_client, company):
        response = platform_client.post(
            reverse("platform:company-approve", kwargs={"pk": company.id})
        )
        assert response.status_code == 409

    def test_suspend_requires_reason_and_stops_jobs(self, platform_client, company):
        missing = platform_client.post(
            reverse("platform:company-suspend", kwargs={"pk": company.id}),
            {},
            format="json",
        )
        assert missing.status_code == 400

        response = platform_client.post(
            reverse("platform:company-suspend", kwargs={"pk": company.id}),
            {"reason": "Lost parcels"},
            format="json",
        )

        assert response.status_code == 200
        company.refresh_from_db()
        assert company.status == CompanyStatus.SUSPENDED
        assert company.is_accepting_jobs is False
        assert company.suspended_reason == "Lost parcels"

    def test_admin_cannot_approve_own_company(self, company_client, company):
        company.status = CompanyStatus.PENDING
        company.save(update_fields=["status"])
        response = company_client.post(
            reverse("platform:company-approve", kwargs={"pk": company.id})
        )
        assert response.status_code == 403

    def test_filter_by_status(self, platform_client, company, other_company):
        company.status = CompanyStatus.SUSPENDED
        company.save(update_fields=["status"])

        response = platform_client.get(
            reverse("platform:company-list"), {"status": CompanyStatus.ACTIVE}
        )

        assert response.data["count"] == 1
        assert response.data["results"][0]["slug"] == other_company.slug


class TestOwnCompany:
    def test_get_and_patch(self, company_client, company):
        detail = company_client.get(reverse("company:company-detail"))
        assert detail.status_code == 200
        assert detail.data["slug"] == company.slug

        patched = company_client.patch(
            reverse("company:company-detail"),
            {"name": "Fast Lane 2", "is_accepting_jobs": False},
            format="json",
        )
        assert patched.status_code == 200
        company.refresh_from_db()
        assert company.name == "Fast Lane 2"
        assert company.is_accepting_jobs is False

    def test_status_and_commission_are_platform_run(self, company_client, company):
        before = company.commission_rate
        response = company_client.patch(
            reverse("company:company-detail"),
            {"status": CompanyStatus.SUSPENDED, "commission_rate": "0.5000"},
            format="json",
        )
        assert response.status_code == 200
        company.refresh_from_db()
        assert company.status == CompanyStatus.ACTIVE
        assert company.commission_rate == before

    def test_customer_cannot_reach_the_company_surface(self, auth_client):
        assert auth_client.get(reverse("company:company-detail")).status_code == 403

    def test_store_admin_cannot_reach_the_company_surface(self, dashboard_client):
        assert dashboard_client.get(reverse("company:company-detail")).status_code == 403

    def test_staff_reads_but_does_not_write(self, company_client, company, courier):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        staff = User.objects.create_user(
            email="dispatch@fastlane.test",
            password=CUSTOMER_PASSWORD,
            full_name="Dispatch",
            role=Role.DELIVERY_STAFF,
        )
        CompanyMembership.objects.create(company=company, user=staff, role=MemberRole.STAFF)
        staff_client = client_for(staff)

        assert staff_client.get(reverse("company:company-detail")).status_code == 200
        write = staff_client.patch(
            reverse("company:company-detail"), {"name": "Hijacked"}, format="json"
        )
        assert write.status_code == 403


class TestZones:
    def _payload(self, name="Downtown"):
        return {
            "name": name,
            "center_lat": "33.510000",
            "center_lng": "36.290000",
            "radius_km": "5.00",
            "fee": "5000.00",
            "min_order_total": "25000.00",
            "eta_minutes": 30,
        }

    def test_create_list_patch_and_retire(self, company_client):
        created = company_client.post(reverse("company:zone-list"), self._payload(), format="json")
        assert created.status_code == 201, created.data
        assert created.data["fee"] == "5000.00"  # money is a string
        zone_id = created.data["id"]

        listed = company_client.get(reverse("company:zone-list"))
        assert listed.data["count"] == 1

        patched = company_client.patch(
            reverse("company:zone-detail", kwargs={"pk": zone_id}),
            {"fee": "6000.00"},
            format="json",
        )
        assert patched.status_code == 200
        assert patched.data["fee"] == "6000.00"

        deleted = company_client.delete(reverse("company:zone-detail", kwargs={"pk": zone_id}))
        assert deleted.status_code == 204
        zone = DeliveryZone.objects.get(pk=zone_id)
        assert zone.is_active is False

    def test_duplicate_name_is_rejected(self, company_client):
        payload = self._payload()
        created = company_client.post(reverse("company:zone-list"), payload, format="json")
        assert created.status_code == 201, created.data

        duplicate = company_client.post(reverse("company:zone-list"), payload, format="json")
        assert duplicate.status_code == 400
        assert "name" in duplicate.data

    def test_another_company_cannot_patch_the_zone(self, other_company_client, company):
        zone = DeliveryZone.objects.create(
            company=company,
            name="Downtown",
            center_lat="33.510000",
            center_lng="36.290000",
            radius_km="5.00",
            fee="5000.00",
            eta_minutes=30,
        )

        response = other_company_client.patch(
            reverse("company:zone-detail", kwargs={"pk": zone.id}),
            {"fee": "1.00"},
            format="json",
        )
        assert response.status_code == 404

    def test_list_only_shows_own_zones(self, company_client, company, other_company):
        DeliveryZone.objects.create(
            company=other_company,
            name="Foreign",
            center_lat="33.510000",
            center_lng="36.290000",
            radius_km="5.00",
            fee="5000.00",
        )

        response = company_client.get(reverse("company:zone-list"))
        assert response.data["count"] == 0


class TestCouriers:
    def test_create_list_and_deactivate(self, company_client, company):
        created = company_client.post(
            reverse("company:courier-list"),
            {
                "email": "rider@fastlane.test",
                "full_name": "Rider One",
                "phone": "+963900000055",
                "vehicle": "motorcycle",
            },
            format="json",
        )

        assert created.status_code == 201, created.data
        assert created.data["full_name"] == "Rider One"
        assert created.data["is_active"] is True

        listed = company_client.get(reverse("company:courier-list"))
        assert listed.data["count"] == 1

        deactivated = company_client.patch(
            reverse("company:courier-detail", kwargs={"pk": created.data["id"]}),
            {"is_active": False},
            format="json",
        )
        assert deactivated.status_code == 200

        profile = CourierProfile.objects.get(pk=created.data["id"])
        assert profile.company == company
        assert profile.user.is_active is False
        assert profile.is_available is False

    def test_search_filters_the_fleet(self, company_client, courier):
        found = company_client.get(reverse("company:courier-list"), {"q": "Courier One"})
        assert found.data["count"] == 1

        missing = company_client.get(reverse("company:courier-list"), {"q": "Nobody"})
        assert missing.data["count"] == 0

    def test_creating_a_store_admin_as_courier_conflicts(self, company_client, store):
        response = company_client.post(
            reverse("company:courier-list"),
            {"email": store.owner.email, "full_name": store.owner.full_name},
            format="json",
        )
        assert response.status_code == 409

    def test_another_company_cannot_deactivate_the_courier(self, other_company_client, courier):
        response = other_company_client.patch(
            reverse("company:courier-detail", kwargs={"pk": courier.courier_profile.id}),
            {"is_active": False},
            format="json",
        )
        assert response.status_code == 404


class TestCompanyTeam:
    def test_invite_manager_and_list(self, company_client):
        invited = company_client.post(
            reverse("company:member-invite"),
            {"email": "manager@fastlane.test", "full_name": "Manager One"},
            format="json",
        )

        assert invited.status_code == 201, invited.data
        assert invited.data["role"] == MemberRole.MANAGER

        listed = company_client.get(reverse("company:member-list"))
        assert listed.data["count"] == 2  # owner + manager

    def test_owner_role_cannot_be_downgraded(self, company_client, company):
        owner_membership = company.memberships.get(role=MemberRole.OWNER)

        response = company_client.patch(
            reverse("company:member-detail", kwargs={"pk": owner_membership.id}),
            {"role": MemberRole.STAFF},
            format="json",
        )
        assert response.status_code == 422

    def test_staff_invite_is_denied(self, company_client, company):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        staff = User.objects.create_user(
            email="dispatch@fastlane.test",
            password=CUSTOMER_PASSWORD,
            full_name="Dispatch",
            role=Role.DELIVERY_STAFF,
        )
        CompanyMembership.objects.create(company=company, user=staff, role=MemberRole.STAFF)
        staff_client = client_for(staff)

        response = staff_client.post(
            reverse("company:member-invite"),
            {"email": "another@fastlane.test", "full_name": "Another"},
            format="json",
        )
        assert response.status_code == 403
