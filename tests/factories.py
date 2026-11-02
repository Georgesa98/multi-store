"""Helpers shared by the test modules.

Factories stay thin: they call the same services the API calls, so tests
exercise the real code paths instead of hand-building rows.
"""

from decimal import Decimal

from core.enums import Vehicle
from delivery import services as delivery_services
from delivery.models import DeliveryZone

CUSTOMER_PASSWORD = "Str0ngPass!23"


def connect(store, company, priority=0):
    """Contract a store with a delivery company."""
    return delivery_services.activate_partner(store=store, company=company, priority=priority)


def zone_for_store(
    store,
    company,
    *,
    name="Downtown",
    fee="5000.00",
    min_order_total="0.00",
    radius_km="6.00",
    center_lat="33.510000",
    center_lng="36.290000",
    eta_minutes=30,
    priority=0,
):
    """A company zone that covers the shared test address, plus the contract."""
    connect(store, company, priority=priority)
    return DeliveryZone.objects.create(
        company=company,
        name=name,
        center_lat=Decimal(center_lat),
        center_lng=Decimal(center_lng),
        radius_km=Decimal(radius_km),
        fee=Decimal(fee),
        min_order_total=Decimal(min_order_total),
        eta_minutes=eta_minutes,
    )


def make_courier(
    company,
    *,
    email="courier@pizza.test",
    full_name="Courier One",
    phone="+963900000003",
    vehicle=Vehicle.MOTORCYCLE,
    password=CUSTOMER_PASSWORD,
):
    profile = delivery_services.create_courier(
        company=company,
        email=email,
        full_name=full_name,
        phone=phone,
        vehicle=vehicle,
    )
    profile.user.set_password(password)
    profile.user.save(update_fields=["password"])
    return profile
