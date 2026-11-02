"""Store business logic: onboarding, status, hours, zones, couriers."""

from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import transaction
from django.utils.text import slugify

from accounts.services import make_password_reset_token
from core.enums import MemberRole, Role, StoreStatus
from core.exceptions import BusinessRuleViolation, Conflict
from stores.models import DeliveryZone, OpeningHours, Store, StoreMembership

User = get_user_model()


def _unique_slug(model, base: str, **scope) -> str:
    base = slugify(base)[:60] or "store"
    candidate = base
    i = 2
    while model.objects.filter(slug=candidate, **scope).exists():
        candidate = f"{base}-{i}"
        i += 1
    return candidate


def _unique_code(base: str) -> str:
    """Short uppercase prefix for order numbers, e.g. Pizza Place -> PIZZAP."""
    letters = "".join(ch for ch in slugify(base).upper() if ch.isalnum())[:8]
    base = letters or "STORE"
    candidate = base
    i = 2
    while Store.objects.filter(code=candidate).exists():
        suffix = str(i)
        candidate = f"{base[: 8 - len(suffix)]}{suffix}"
        i += 1
    return candidate


def derive_store_code(name: str) -> str:
    """Public helper so onboarding and seeding agree on the prefix."""
    return _unique_code(name)


def _send_invite(user, store: Store | None = None) -> None:
    uid, token = make_password_reset_token(user)
    from django.conf import settings

    url = f"{settings.FRONTEND_URL}/reset-password?uid={uid}&token={token}"
    where = f" for {store.name}" if store else ""
    send_mail(
        subject="You have been invited",
        message=f"Set your password to activate your account{where}: {url}",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=True,
    )


@transaction.atomic
def create_store_with_owner(
    *, name, owner_email, owner_full_name, slug="", code="", owner_phone="", **fields
):
    """Platform onboarding: one store, one owner, one membership."""
    owner = User.objects.filter(email__iexact=owner_email).first()
    created_owner = owner is None

    if created_owner:
        owner = User.objects.create_user(
            email=owner_email,
            password=None,
            full_name=owner_full_name,
            phone=owner_phone,
            role=Role.STORE_ADMIN,
        )
        owner.set_unusable_password()
        owner.save(update_fields=["password"])
    elif owner.role not in (Role.STORE_ADMIN, Role.STORE_STAFF):
        raise BusinessRuleViolation(
            {"owner_email": ["This account already exists with a different role."]}
        )

    existing = StoreMembership.objects.filter(user=owner, is_active=True).first()
    if existing is not None:
        raise Conflict(
            {
                "owner_email": [
                    "This user already manages a store; v1 allows one active store per admin."
                ]
            }
        )

    store = Store.objects.create(
        owner=owner,
        name=name,
        slug=slug or _unique_slug(Store, name),
        code=code or _unique_code(name),
        **fields,
    )
    StoreMembership.objects.create(store=store, user=owner, role=MemberRole.OWNER)

    if created_owner:
        _send_invite(owner, store)
    return store


@transaction.atomic
def approve_store(store: Store) -> Store:
    if store.status != StoreStatus.PENDING:
        raise Conflict({"detail": f"Store is {store.status}, not pending."})
    store.status = StoreStatus.ACTIVE
    store.is_accepting_orders = True
    store.save(update_fields=["status", "is_accepting_orders", "updated_at"])
    return store


@transaction.atomic
def suspend_store(store: Store, reason: str) -> Store:
    if store.status == StoreStatus.SUSPENDED:
        raise Conflict({"detail": "Store is already suspended."})
    store.status = StoreStatus.SUSPENDED
    store.is_accepting_orders = False
    store.suspended_reason = reason
    store.save(
        update_fields=[
            "status",
            "is_accepting_orders",
            "suspended_reason",
            "updated_at",
        ]
    )
    return store


@transaction.atomic
def replace_opening_hours(store: Store, rows: list[dict]) -> list[OpeningHours]:
    """Bulk replace: whatever is not in `rows` is removed."""
    store.opening_hours.all().delete()
    created = [
        OpeningHours.objects.create(
            store=store,
            weekday=row["weekday"],
            open_time=row["open_time"],
            close_time=row["close_time"],
            is_closed=row.get("is_closed", False),
        )
        for row in rows
    ]
    return created


@transaction.atomic
def invite_courier(*, store: Store, email: str, full_name: str, phone: str = "") -> User:
    user = User.objects.filter(email__iexact=email).first()
    if user is not None:
        if user.role != Role.COURIER:
            raise Conflict({"email": ["This account already exists with a different role."]})
        if hasattr(user, "courier_profile"):
            raise Conflict({"email": ["This courier is already registered."]})
        if user.courier_profile.store_id != store.id:  # pragma: no cover - defensive
            raise Conflict({"email": ["This courier belongs to another store."]})
    else:
        user = User.objects.create_user(
            email=email,
            password=None,
            full_name=full_name,
            phone=phone,
            role=Role.COURIER,
        )
        user.set_unusable_password()
        user.save(update_fields=["password"])
        _send_invite(user, store)

    from accounts.models import CourierProfile

    CourierProfile.objects.create(user=user, store=store)
    return user


@transaction.atomic
def deactivate_courier(profile) -> None:
    profile.is_available = False
    profile.save(update_fields=["is_available", "updated_at"])
    user = profile.user
    user.is_active = False
    user.save(update_fields=["is_active"])


def zone_for_point(store: Store, lat, lng) -> DeliveryZone | None:
    """Smallest active zone that contains the point, or None."""
    from core.geo import haversine_km

    candidates = [
        z
        for z in store.zones.filter(is_active=True)
        if haversine_km(lat, lng, z.center_lat, z.center_lng) <= float(z.radius_km)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda z: float(z.radius_km))
