"""Idempotent demo data for local development.

Grows with the build: Phase 0 seeds users, Phase 1 adds a store with its
catalogue and a courier. Safe to run repeatedly.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import CourierProfile, CustomerProfile
from catalog.models import Category, Product, ProductVariant
from core.enums import MemberRole, ProductStatus, Role, StoreStatus, Vehicle
from stores.models import DeliveryZone, OpeningHours, Store, StoreMembership

User = get_user_model()

STORE_SLUG = "pizza-place"
COURIER_EMAIL = "courier@pizza.example"


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

        created += self._seed_store(password)
        created += self._seed_courier(password)

        if created:
            self.stdout.write(self.style.SUCCESS("Created: " + ", ".join(created)))
        else:
            self.stdout.write("Nothing to create - demo data already present.")
        self.stdout.write(f"Demo password: {password}")

    # -- store + catalogue ---------------------------------------------------

    def _seed_store(self, password):
        created = []

        owner, was_created = self._ensure_user(
            email="owner@pizza.example",
            full_name="Pizza Owner",
            role=Role.STORE_ADMIN,
            password=password,
        )
        created += self._report(owner, was_created)

        store, store_created = Store.objects.get_or_create(
            slug=STORE_SLUG,
            defaults={
                "owner": owner,
                "name": "Pizza Place",
                "description": "Wood-fired pizza, delivered by our own riders.",
                "phone": "+963900000010",
                "address_text": "Al-Hamidiya, Damascus",
                "status": StoreStatus.ACTIVE,
                "lat": Decimal("33.510000"),
                "lng": Decimal("36.290000"),
            },
        )
        if store_created:
            created.append(store.slug)

        StoreMembership.objects.get_or_create(
            store=store,
            user=owner,
            defaults={"role": MemberRole.OWNER},
        )

        if not store.opening_hours.exists():
            OpeningHours.objects.bulk_create(
                [
                    OpeningHours(
                        store=store,
                        weekday=day,
                        open_time="09:00",
                        close_time="23:00",
                        is_closed=day == 6,
                    )
                    for day in range(7)
                ]
            )

        if not store.zones.exists():
            DeliveryZone.objects.create(
                store=store,
                name="Downtown",
                center_lat=Decimal("33.510000"),
                center_lng=Decimal("36.290000"),
                radius_km=Decimal("6.00"),
                fee=Decimal("5000.00"),
                min_order_total=Decimal("15000.00"),
                eta_minutes=30,
            )

        pizza, _ = Category.objects.get_or_create(
            store=store, slug="pizza", defaults={"name": "Pizza", "sort_order": 1}
        )
        drinks, _ = Category.objects.get_or_create(
            store=store, slug="drinks", defaults={"name": "Drinks", "sort_order": 2}
        )

        self._seed_product(
            store,
            category=pizza,
            name="Margherita",
            slug="margherita",
            price=Decimal("12000.00"),
            stock=50,
        )
        self._seed_product(
            store,
            category=pizza,
            name="Pepperoni",
            slug="pepperoni",
            price=Decimal("15000.00"),
            stock=40,
        )
        self._seed_product(
            store,
            category=drinks,
            name="Cola",
            slug="cola",
            price=Decimal("3000.00"),
            stock=100,
        )

        return created

    def _seed_product(self, store, *, category, name, slug, price, stock):
        product, _ = Product.objects.get_or_create(
            store=store,
            slug=slug,
            defaults={
                "name": name,
                "category": category,
                "description": f"Fresh {name.lower()}.",
                "status": ProductStatus.ACTIVE,
            },
        )
        ProductVariant.objects.get_or_create(
            product=product,
            label="Default",
            defaults={
                "sku": f"{STORE_SLUG}-{slug}-default".upper(),
                "price": price,
                "stock_qty": stock,
            },
        )

    def _seed_courier(self, password):
        store = Store.objects.filter(slug=STORE_SLUG).first()
        if store is None:
            return []

        courier, was_created = self._ensure_user(
            email=COURIER_EMAIL,
            full_name="Courier One",
            role=Role.COURIER,
            password=password,
            phone="+963900000020",
        )
        CourierProfile.objects.get_or_create(
            user=courier,
            defaults={"store": store, "vehicle": Vehicle.MOTORCYCLE},
        )
        return self._report(courier, was_created)

    # -- helpers -------------------------------------------------------------

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
