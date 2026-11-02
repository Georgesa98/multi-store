"""Idempotent demo data for local development.

Grows with the build: Phase 0 seeds users, Phase 1 a store with its catalogue,
Phase 2 a saved address and coupons, Phase 3 a delivery company with its zones,
partner contract and courier. Safe to run repeatedly.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import Address, CourierProfile, CustomerProfile
from catalog.models import Category, Product, ProductVariant
from core.enums import (
    CompanyStatus,
    CouponType,
    MemberRole,
    ProductStatus,
    Role,
    StoreStatus,
    Vehicle,
)
from delivery.models import CompanyMembership, DeliveryCompany, DeliveryZone, StoreDeliveryPartner
from orders.models import Coupon
from stores.models import OpeningHours, Store, StoreMembership

User = get_user_model()

STORE_SLUG = "pizza-place"
COMPANY_SLUG = "fast-lane"
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
        created += self._seed_delivery(password)
        created += self._seed_addresses()
        created += self._seed_coupons()

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
                "code": "PIZ",
                "name": "Pizza Place",
                "description": "Wood-fired pizza, delivered by our delivery partners.",
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

    def _seed_delivery(self, password):
        """A delivery company, its zones, its courier, and the store's contract."""
        created = []

        owner, was_created = self._ensure_user(
            email="delivery@pizza.example",
            full_name="Fast Lane Owner",
            role=Role.DELIVERY_ADMIN,
            password=password,
            phone="+963900000030",
        )
        created += self._report(owner, was_created)

        company, company_created = DeliveryCompany.objects.get_or_create(
            slug=COMPANY_SLUG,
            defaults={
                "owner": owner,
                "name": "Fast Lane Delivery",
                "description": "Same-day courier fleet across Damascus.",
                "phone": "+963900000031",
                "address_text": "Bab Touma, Damascus",
                "status": CompanyStatus.ACTIVE,
                "lat": Decimal("33.510000"),
                "lng": Decimal("36.290000"),
            },
        )
        if company_created:
            created.append(company.slug)

        CompanyMembership.objects.get_or_create(
            company=company,
            user=owner,
            defaults={"role": MemberRole.OWNER},
        )

        zones = (
            (
                "Downtown",
                Decimal("33.510000"),
                Decimal("36.290000"),
                Decimal("6.00"),
                Decimal("5000.00"),
                Decimal("15000.00"),
                30,
            ),
            (
                "Greater Damascus",
                Decimal("33.510000"),
                Decimal("36.290000"),
                Decimal("18.00"),
                Decimal("9000.00"),
                Decimal("25000.00"),
                50,
            ),
        )
        for name, lat, lng, radius, fee, minimum, eta in zones:
            _, zone_created = DeliveryZone.objects.get_or_create(
                company=company,
                name=name,
                defaults={
                    "center_lat": lat,
                    "center_lng": lng,
                    "radius_km": radius,
                    "fee": fee,
                    "min_order_total": minimum,
                    "eta_minutes": eta,
                },
            )
            if zone_created:
                created.append(f"{company.slug}:{name}")

        store = Store.objects.filter(slug=STORE_SLUG).first()
        if store is not None:
            _, partner_created = StoreDeliveryPartner.objects.get_or_create(
                store=store,
                company=company,
                defaults={"priority": 0},
            )
            if partner_created:
                created.append("partner")

        courier, was_created = self._ensure_user(
            email=COURIER_EMAIL,
            full_name="Courier One",
            role=Role.COURIER,
            password=password,
            phone="+963900000020",
        )
        created += self._report(courier, was_created)
        CourierProfile.objects.update_or_create(
            user=courier,
            defaults={"company": company, "vehicle": Vehicle.MOTORCYCLE},
        )

        return created

    # -- customer address book -----------------------------------------------

    def _seed_addresses(self):
        created = []
        customer = User.objects.filter(email="customer@example.com").first()
        if customer is None:
            return created

        profile, _ = CustomerProfile.objects.get_or_create(user=customer)
        if not customer.addresses.exists():
            Address.objects.create(
                customer=customer,
                label="Home",
                line1="Al-Hamidiya Street 12",
                city="Damascus",
                lat=Decimal("33.510000"),
                lng=Decimal("36.290000"),
                is_default=True,
            )
            created.append("address")

        address = customer.addresses.first()
        if address is not None and profile.default_address_id is None:
            profile.default_address = address
            profile.save(update_fields=["default_address", "updated_at"])
        return created

    # -- coupons -------------------------------------------------------------

    def _seed_coupons(self):
        created = []
        store = Store.objects.filter(slug=STORE_SLUG).first()
        if store is not None:
            _, was_created = Coupon.objects.get_or_create(
                store=store,
                code="PIZZA10",
                defaults={
                    "discount_type": CouponType.PERCENT,
                    "value": Decimal("10.00"),
                    "min_order_total": Decimal("15000.00"),
                    "max_discount": Decimal("5000.00"),
                },
            )
            if was_created:
                created.append("PIZZA10")

        _, was_created = Coupon.objects.get_or_create(
            store=None,
            code="WELCOME5",
            defaults={
                "discount_type": CouponType.FIXED,
                "value": Decimal("5000.00"),
                "min_order_total": Decimal("10000.00"),
            },
        )
        if was_created:
            created.append("WELCOME5")
        return created

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
