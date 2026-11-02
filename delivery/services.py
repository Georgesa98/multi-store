"""Delivery-company business logic: onboarding, zones, dispatch and fulfilment."""

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.text import slugify

from accounts.services import send_invite
from core.enums import (
    CompanyStatus,
    DeliveryAction,
    DeliveryStatus,
    MemberRole,
    OrderStatus,
    Role,
    Vehicle,
)
from core.exceptions import BusinessRuleViolation, Conflict
from core.geo import haversine_km
from core.money import money
from delivery.models import (
    CompanyMembership,
    CourierLocation,
    Delivery,
    DeliveryCompany,
    DeliveryEvent,
    DeliveryLocationPing,
    DeliveryZone,
    StoreDeliveryPartner,
)
from delivery.realtime import broadcast_location, broadcast_status
from notifications import services as notification_services

User = get_user_model()

ACTIVE_DELIVERY_STATUSES = (
    DeliveryStatus.UNASSIGNED,
    DeliveryStatus.REQUESTED,
    DeliveryStatus.OFFERED,
    DeliveryStatus.ACCEPTED,
    DeliveryStatus.PICKED_UP,
)


# ---------------------------------------------------------------------------
# Companies
# ---------------------------------------------------------------------------


def _unique_slug(model, base: str, **scope) -> str:
    base = slugify(base)[:60] or "company"
    candidate = base
    i = 2
    while model.objects.filter(slug=candidate, **scope).exists():
        candidate = f"{base}-{i}"
        i += 1
    return candidate


@transaction.atomic
def create_company_with_owner(
    *, name, owner_email, owner_full_name, slug="", owner_phone="", **fields
) -> DeliveryCompany:
    """Platform onboarding: one company, one owner, one membership."""
    owner = User.objects.filter(email__iexact=owner_email).first()
    created_owner = owner is None

    if created_owner:
        owner = User.objects.create_user(
            email=owner_email,
            password=None,
            full_name=owner_full_name,
            phone=owner_phone,
            role=Role.DELIVERY_ADMIN,
        )
        owner.set_unusable_password()
        owner.save(update_fields=["password"])
    elif owner.role not in (Role.DELIVERY_ADMIN, Role.DELIVERY_STAFF):
        raise BusinessRuleViolation(
            {"owner_email": ["This account already exists with a different role."]}
        )

    existing = CompanyMembership.objects.filter(user=owner, is_active=True).first()
    if existing is not None:
        raise Conflict(
            {
                "owner_email": [
                    "This user already manages a delivery company; "
                    "v1 allows one active company per admin."
                ]
            }
        )

    company = DeliveryCompany.objects.create(
        owner=owner,
        name=name,
        slug=slug or _unique_slug(DeliveryCompany, name),
        **fields,
    )
    CompanyMembership.objects.create(company=company, user=owner, role=MemberRole.OWNER)

    if created_owner:
        send_invite(owner, company)
    return company


@transaction.atomic
def approve_company(company: DeliveryCompany) -> DeliveryCompany:
    if company.status != CompanyStatus.PENDING:
        raise Conflict({"detail": f"Company is {company.status}, not pending."})
    company.status = CompanyStatus.ACTIVE
    company.is_accepting_jobs = True
    company.save(update_fields=["status", "is_accepting_jobs", "updated_at"])
    return company


@transaction.atomic
def suspend_company(company: DeliveryCompany, reason: str) -> DeliveryCompany:
    if company.status == CompanyStatus.SUSPENDED:
        raise Conflict({"detail": "Company is already suspended."})
    company.status = CompanyStatus.SUSPENDED
    company.is_accepting_jobs = False
    company.suspended_reason = reason
    company.save(update_fields=["status", "is_accepting_jobs", "suspended_reason", "updated_at"])
    return company


@transaction.atomic
def invite_company_member(
    *, company: DeliveryCompany, email, full_name, phone="", role=MemberRole.MANAGER
):
    user = User.objects.filter(email__iexact=email).first()
    created = user is None
    if created:
        user = User.objects.create_user(
            email=email,
            password=None,
            full_name=full_name,
            phone=phone,
            role=Role.DELIVERY_STAFF,
        )
        user.set_unusable_password()
        user.save(update_fields=["password"])
    elif user.role not in (Role.DELIVERY_ADMIN, Role.DELIVERY_STAFF):
        raise Conflict({"email": ["This account already exists with a different role."]})

    if CompanyMembership.objects.filter(company=company, user=user).exists():
        raise Conflict({"email": ["This user is already on the company team."]})
    if CompanyMembership.objects.filter(user=user, is_active=True).exists():
        raise Conflict({"email": ["This user already belongs to another delivery company."]})

    membership = CompanyMembership.objects.create(company=company, user=user, role=role)
    if created:
        send_invite(user, company)
    return membership


@transaction.atomic
def set_company_member_active(membership: CompanyMembership, is_active: bool):
    membership.is_active = is_active
    membership.save(update_fields=["is_active", "updated_at"])
    return membership


# ---------------------------------------------------------------------------
# Couriers
# ---------------------------------------------------------------------------


@transaction.atomic
def create_courier(*, company, email, full_name, phone="", vehicle=Vehicle.MOTORCYCLE, plate=""):
    """Companies own their riders; stores never create one."""
    user = User.objects.filter(email__iexact=email).first()
    created = user is None
    if created:
        user = User.objects.create_user(
            email=email,
            password=None,
            full_name=full_name,
            phone=phone,
            role=Role.COURIER,
        )
        user.set_unusable_password()
        user.save(update_fields=["password"])
    elif user.role != Role.COURIER:
        raise Conflict({"email": ["This account already exists with a different role."]})
    elif hasattr(user, "courier_profile"):
        raise Conflict({"email": ["This courier is already registered."]})

    from accounts.models import CourierProfile

    profile = CourierProfile.objects.create(
        user=user,
        company=company,
        vehicle=vehicle,
        plate=plate,
    )
    if created:
        send_invite(user, company)
    return profile


@transaction.atomic
def deactivate_courier(profile) -> None:
    profile.is_available = False
    profile.save(update_fields=["is_available", "updated_at"])
    user = profile.user
    user.is_active = False
    user.save(update_fields=["is_active"])


# ---------------------------------------------------------------------------
# Store <-> company contracts and zones
# ---------------------------------------------------------------------------


def partners_for_store(store) -> list[StoreDeliveryPartner]:
    """Active contracts, best (lowest priority number) first."""
    return list(
        StoreDeliveryPartner.objects.filter(
            store=store,
            is_active=True,
            company__status=CompanyStatus.ACTIVE,
        )
        .select_related("company")
        .order_by("priority", "company__name")
    )


@transaction.atomic
def activate_partner(*, store, company, priority=0) -> StoreDeliveryPartner:
    if company.status != CompanyStatus.ACTIVE:
        raise BusinessRuleViolation({"company": ["This company is not active."]})
    partner, _ = StoreDeliveryPartner.objects.get_or_create(
        store=store, company=company, defaults={"priority": priority}
    )
    if not partner.is_active or partner.priority != priority:
        partner.is_active = True
        partner.priority = priority
        partner.save(update_fields=["is_active", "priority", "updated_at"])
    return partner


@transaction.atomic
def set_partner(partner: StoreDeliveryPartner, **fields) -> StoreDeliveryPartner:
    allowed = {"is_active", "priority"}
    for key, value in fields.items():
        if key in allowed:
            setattr(partner, key, value)
    partner.save(update_fields=["is_active", "priority", "updated_at"])
    return partner


def zone_for_point(company, lat, lng) -> DeliveryZone | None:
    """Smallest active zone of this company that contains the point."""
    candidates = [
        zone
        for zone in company.zones.filter(is_active=True)
        if haversine_km(lat, lng, zone.center_lat, zone.center_lng) <= float(zone.radius_km)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda zone: float(zone.radius_km))


def quote_for_store(store, lat, lng):
    """(company, zone) for a store's top-priority partner covering the point."""
    for partner in partners_for_store(store):
        company = partner.company
        if not company.is_accepting_jobs:
            continue
        zone = zone_for_point(company, lat, lng)
        if zone is not None:
            return company, zone
    return None


# ---------------------------------------------------------------------------
# Order <-> delivery
# ---------------------------------------------------------------------------


def create_for_order(*, order, company, zone, fee) -> Delivery:
    """Created at checkout so the quoted company and fee are locked in."""
    return Delivery.objects.create(
        store=order.store,
        order=order,
        company=company,
        zone=zone,
        status=DeliveryStatus.UNASSIGNED,
        fee=money(fee),
        cash_to_collect=order.total,
    )


def _event(
    delivery,
    action,
    *,
    actor=None,
    from_courier=None,
    to_courier=None,
    from_company=None,
    note="",
):
    event = DeliveryEvent.objects.create(
        delivery=delivery,
        from_courier=from_courier,
        to_courier=to_courier,
        from_company=from_company or delivery.company,
        to_company=delivery.company,
        action=action,
        actor=actor,
        note=note,
    )
    broadcast_status(delivery)
    return event


def _move_order(order, to_status, actor, note="", request_delivery=True):
    """Order status changes stay inside the orders state machine."""
    from orders.services import transition

    return transition(
        order=order,
        to_status=to_status,
        actor=actor,
        note=note,
        request_delivery=request_delivery,
    )


@transaction.atomic
def request_delivery(delivery: Delivery, *, actor=None, company=None) -> Delivery:
    """Ask (or re-ask) a company to take the job; `ready` triggers this."""
    delivery = (
        Delivery.objects.select_for_update(of=("self",))
        .select_related("order", "company")
        .get(pk=delivery.pk)
    )
    order = delivery.order

    if delivery.status == DeliveryStatus.CANCELLED:
        raise Conflict({"detail": "This delivery was cancelled."})
    if delivery.status in (DeliveryStatus.ACCEPTED, DeliveryStatus.PICKED_UP):
        raise Conflict({"detail": "This delivery is already being handled."})
    if order.status != OrderStatus.READY:
        raise BusinessRuleViolation(
            {"detail": "The order must be ready before it is requested from a company."}
        )

    previous_company = delivery.company
    if company is not None and company.id != delivery.company_id:
        contracted = StoreDeliveryPartner.objects.filter(
            store_id=delivery.store_id,
            company=company,
            is_active=True,
            company__status=CompanyStatus.ACTIVE,
        ).exists()
        if not contracted:
            raise BusinessRuleViolation(
                {"company_id": ["This store has no active contract with that company."]}
            )
        delivery.company = company
    if delivery.company is None:
        raise BusinessRuleViolation({"detail": "This order has no delivery company."})
    if delivery.status == DeliveryStatus.FAILED:
        delivery.assign_attempts += 1

    delivery.status = DeliveryStatus.REQUESTED
    delivery.requested_at = timezone.now()
    delivery.offered_at = delivery.requested_at
    delivery.courier = None
    delivery.save(
        update_fields=[
            "company",
            "status",
            "requested_at",
            "offered_at",
            "courier",
            "assign_attempts",
            "updated_at",
        ]
    )
    _event(
        delivery,
        DeliveryAction.REQUESTED,
        actor=actor,
        from_company=previous_company,
    )
    notification_services.job_requested(delivery)
    return delivery


@transaction.atomic
def assign_courier(delivery: Delivery, *, courier, actor) -> Delivery:
    """Dispatcher assignment (or reassignment) inside the delivery's company."""
    delivery = (
        Delivery.objects.select_for_update(of=("self",))
        .select_related("order", "company")
        .get(pk=delivery.pk)
    )
    if delivery.status in (DeliveryStatus.DELIVERED, DeliveryStatus.CANCELLED):
        raise Conflict({"detail": f"This delivery is {delivery.status}."})
    if delivery.courier_id is not None and delivery.courier_id != courier.id:
        raise Conflict({"detail": "Release or reassign the current courier first."})
    if courier.courier_profile.company_id != delivery.company_id:
        raise BusinessRuleViolation({"detail": "That courier works for another company."})

    if delivery.status == DeliveryStatus.UNASSIGNED:
        delivery.status = DeliveryStatus.REQUESTED
        delivery.requested_at = timezone.now()
    previous_courier_id = delivery.courier_id
    delivery.courier = courier
    delivery.status = DeliveryStatus.ACCEPTED
    delivery.accepted_at = timezone.now()
    delivery.save(update_fields=["courier", "status", "requested_at", "accepted_at", "updated_at"])

    order = delivery.order
    if order.status == OrderStatus.READY:
        _move_order(order, OrderStatus.ASSIGNED, actor, note="Courier assigned")
    _event(
        delivery,
        DeliveryAction.REASSIGNED if previous_courier_id else DeliveryAction.ASSIGNED,
        actor=actor,
        to_courier=courier,
    )
    notification_services.courier_assigned(delivery, courier)
    return delivery


@transaction.atomic
def release_delivery(delivery: Delivery, *, actor, note="") -> Delivery:
    """Company hands the job back: the store may pick another partner."""
    delivery = Delivery.objects.select_for_update().select_related("order").get(pk=delivery.pk)
    if delivery.status in (DeliveryStatus.DELIVERED, DeliveryStatus.CANCELLED):
        raise Conflict({"detail": f"This delivery is {delivery.status}."})

    previous_courier = delivery.courier
    delivery.courier = None
    delivery.status = DeliveryStatus.UNASSIGNED
    delivery.assign_attempts += 1
    delivery.save(update_fields=["courier", "status", "assign_attempts", "updated_at"])
    if delivery.order.status in (OrderStatus.ASSIGNED, OrderStatus.OUT_FOR_DELIVERY):
        # Leave the order ready without offering it straight back to the
        # company that just released it.
        _move_order(
            delivery.order,
            OrderStatus.READY,
            actor,
            note=note or "Released",
            request_delivery=False,
        )
    _event(
        delivery,
        DeliveryAction.RELEASED,
        actor=actor,
        from_courier=previous_courier,
        note=note,
    )
    return delivery


# ---------------------------------------------------------------------------
# Courier actions
# ---------------------------------------------------------------------------


def offers_for_courier(courier) -> list[Delivery]:
    company_id = courier.courier_profile.company_id
    return list(
        Delivery.objects.filter(company_id=company_id, status=DeliveryStatus.REQUESTED)
        .select_related("order__store", "company")
        .order_by("offered_at")
    )


@transaction.atomic
def accept_offer(delivery: Delivery, *, courier) -> Delivery:
    delivery = (
        Delivery.objects.select_for_update(of=("self",))
        .select_related("order", "company")
        .get(pk=delivery.pk)
    )
    if delivery.company_id != courier.courier_profile.company_id:
        raise BusinessRuleViolation({"detail": "That job belongs to another company."})
    if delivery.status != DeliveryStatus.REQUESTED:
        raise Conflict({"detail": "This job is no longer available."})

    delivery.courier = courier
    delivery.status = DeliveryStatus.ACCEPTED
    delivery.accepted_at = timezone.now()
    delivery.save(update_fields=["courier", "status", "accepted_at", "updated_at"])
    if delivery.order.status == OrderStatus.READY:
        _move_order(delivery.order, OrderStatus.ASSIGNED, courier, note="Courier accepted")
    _event(delivery, DeliveryAction.ACCEPTED, actor=courier, to_courier=courier)
    return delivery


@transaction.atomic
def decline_offer(delivery: Delivery, *, courier, note="") -> Delivery:
    if delivery.company_id != courier.courier_profile.company_id:
        raise BusinessRuleViolation({"detail": "That job belongs to another company."})
    delivery = Delivery.objects.select_for_update().get(pk=delivery.pk)
    if delivery.status != DeliveryStatus.REQUESTED:
        raise Conflict({"detail": "This job is no longer available."})
    delivery.assign_attempts += 1
    delivery.save(update_fields=["assign_attempts", "updated_at"])
    _event(delivery, DeliveryAction.DECLINED, actor=courier, note=note)
    return delivery


@transaction.atomic
def pickup(delivery: Delivery, *, courier) -> Delivery:
    delivery = Delivery.objects.select_for_update().select_related("order").get(pk=delivery.pk)
    if delivery.courier_id != courier.id:
        raise BusinessRuleViolation({"detail": "This delivery is assigned to another courier."})
    if delivery.status != DeliveryStatus.ACCEPTED:
        raise Conflict({"detail": "Accept the job before picking it up."})

    delivery.status = DeliveryStatus.PICKED_UP
    delivery.picked_up_at = timezone.now()
    delivery.save(update_fields=["status", "picked_up_at", "updated_at"])
    if delivery.order.status == OrderStatus.ASSIGNED:
        _move_order(delivery.order, OrderStatus.OUT_FOR_DELIVERY, courier)
    _event(delivery, DeliveryAction.PICKED_UP, actor=courier)
    return delivery


@transaction.atomic
def deliver(
    delivery: Delivery, *, courier, otp="", proof_photo=None, note="", actor=None
) -> Delivery:
    delivery = Delivery.objects.select_for_update().select_related("order").get(pk=delivery.pk)
    if delivery.courier_id != courier.id:
        raise BusinessRuleViolation({"detail": "This delivery is assigned to another courier."})
    if delivery.status not in (DeliveryStatus.ACCEPTED, DeliveryStatus.PICKED_UP):
        raise Conflict({"detail": "Only an active delivery can be completed."})

    now = timezone.now()
    delivery.status = DeliveryStatus.DELIVERED
    delivery.delivered_at = now
    delivery.cash_collected = delivery.cash_to_collect
    delivery.cash_collected_at = now
    delivery.proof_otp = otp or ""
    delivery.proof_note = note or ""
    if proof_photo is not None:
        delivery.proof_photo = proof_photo
    delivery.save(
        update_fields=[
            "status",
            "delivered_at",
            "cash_collected",
            "cash_collected_at",
            "proof_otp",
            "proof_note",
            "proof_photo",
            "updated_at",
        ]
    )
    if delivery.order.status == OrderStatus.OUT_FOR_DELIVERY:
        _move_order(delivery.order, OrderStatus.DELIVERED, courier)
    elif delivery.order.status == OrderStatus.ASSIGNED:
        _move_order(delivery.order, OrderStatus.OUT_FOR_DELIVERY, courier)
        _move_order(delivery.order, OrderStatus.DELIVERED, courier)
    _event(delivery, DeliveryAction.DELIVERED, actor=actor or courier, note=note)

    profile = courier.courier_profile
    profile.deliveries_count += 1
    profile.is_available = True
    profile.save(update_fields=["deliveries_count", "is_available", "updated_at"])
    return delivery


@transaction.atomic
def fail(delivery: Delivery, *, actor, reason) -> Delivery:
    delivery = Delivery.objects.select_for_update().select_related("order").get(pk=delivery.pk)
    if delivery.status in (
        DeliveryStatus.DELIVERED,
        DeliveryStatus.FAILED,
        DeliveryStatus.CANCELLED,
    ):
        raise Conflict({"detail": f"This delivery is already {delivery.status}."})
    if not reason:
        raise BusinessRuleViolation({"reason": ["A failure reason is required."]})

    delivery.status = DeliveryStatus.FAILED
    delivery.failed_at = timezone.now()
    delivery.failure_reason = reason
    delivery.save(update_fields=["status", "failed_at", "failure_reason", "updated_at"])
    order = delivery.order
    if order.status in (OrderStatus.ASSIGNED, OrderStatus.OUT_FOR_DELIVERY):
        _move_order(order, OrderStatus.READY, actor, note=reason)
    _event(delivery, DeliveryAction.FAILED, actor=actor, note=reason)
    notification_services.job_returned(delivery, reason)
    return delivery


@transaction.atomic
def cancel_delivery(delivery: Delivery, *, actor=None, note="") -> Delivery:
    delivery = Delivery.objects.select_for_update().get(pk=delivery.pk)
    if delivery.status in (DeliveryStatus.DELIVERED, DeliveryStatus.CANCELLED):
        return delivery
    delivery.status = DeliveryStatus.CANCELLED
    delivery.courier = None
    delivery.save(update_fields=["status", "courier", "updated_at"])
    _event(delivery, DeliveryAction.CANCELLED, actor=actor, note=note)
    return delivery


# ---------------------------------------------------------------------------
# Tracking and earnings
# ---------------------------------------------------------------------------


def record_location(
    *, delivery: Delivery, courier, lat, lng, accuracy_m=None, heading=None
) -> CourierLocation:
    """Latest position plus a sampled trail, one ping per minute."""
    location, _ = CourierLocation.objects.update_or_create(
        courier=courier,
        defaults={
            "lat": lat,
            "lng": lng,
            "accuracy_m": accuracy_m,
            "heading": heading,
            "is_online": True,
        },
    )
    last = delivery.location_pings.order_by("-created_at").first()
    if last is None or (timezone.now() - last.created_at).total_seconds() >= 60:
        DeliveryLocationPing.objects.create(delivery=delivery, lat=lat, lng=lng)
    broadcast_location(delivery.id, lat=lat, lng=lng)
    return location


def courier_stats(courier) -> dict:
    today = timezone.localdate()
    completed = Delivery.objects.filter(courier=courier, status=DeliveryStatus.DELIVERED)
    today_count = completed.filter(delivered_at__date=today).count()
    return {
        "deliveries_count": courier.courier_profile.deliveries_count,
        "delivered_today": today_count,
    }


def courier_earnings(courier, *, from_date=None, to_date=None) -> dict:
    qs = Delivery.objects.filter(courier=courier, status=DeliveryStatus.DELIVERED)
    if from_date:
        qs = qs.filter(delivered_at__date__gte=from_date)
    if to_date:
        qs = qs.filter(delivered_at__date__lte=to_date)
    totals = qs.aggregate(cash=Sum("cash_collected"), fees=Sum("fee"))
    return {
        "deliveries": qs.count(),
        "cash_collected": money(totals["cash"] or 0),
        "delivery_fees": money(totals["fees"] or 0),
    }


def company_earnings(company, *, from_date=None, to_date=None) -> dict:
    qs = Delivery.objects.filter(company=company, status=DeliveryStatus.DELIVERED)
    if from_date:
        qs = qs.filter(delivered_at__date__gte=from_date)
    if to_date:
        qs = qs.filter(delivered_at__date__lte=to_date)
    totals = qs.aggregate(cash=Sum("cash_collected"), fees=Sum("fee"))
    gross_fees = money(totals["fees"] or 0)
    commission = money(gross_fees * company.commission_rate)
    return {
        "deliveries": qs.count(),
        "cash_collected": money(totals["cash"] or 0),
        "gross_fees": gross_fees,
        "platform_commission": commission,
        "net_fees": money(gross_fees - commission),
    }
