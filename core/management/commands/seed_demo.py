"""Idempotent demo data for local development.

Grows with the build: Phase 0 seeds users, later phases add stores, catalogue,
carts and orders. Safe to run repeatedly.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import CustomerProfile
from core.enums import Role

User = get_user_model()


class Command(BaseCommand):
    help = "Seed demo data (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--password",
            default="Demo12345!",
            help="Password given to every seeded account.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        password = options["password"]
        created = []

        admin, was_created = self._ensure_user(
            email="admin@example.com",
            full_name="Platform Admin",
            role=Role.SUPER_ADMIN,
            password=password,
            is_staff=True,
            is_superuser=True,
        )
        created += self._report(admin, was_created)

        for email, full_name in (
            ("customer@example.com", "Customer One"),
            ("customer2@example.com", "Customer Two"),
        ):
            customer, was_created = self._ensure_user(
                email=email,
                full_name=full_name,
                role=Role.CUSTOMER,
                password=password,
            )
            CustomerProfile.objects.get_or_create(user=customer)
            created += self._report(customer, was_created)

        if created:
            self.stdout.write(self.style.SUCCESS("Created: " + ", ".join(created)))
        else:
            self.stdout.write("Nothing to create — demo data already present.")
        self.stdout.write(f"Demo password: {password}")

    def _ensure_user(self, *, email, full_name, role, password, **flags):
        user = User.objects.filter(email=email).first()
        if user is not None:
            return user, False
        user = User(
            email=email,
            full_name=full_name,
            role=role,
            **flags,
        )
        user.set_password(password)
        user.save()
        return user, True

    def _report(self, user, was_created):
        return [user.email] if was_created else []
