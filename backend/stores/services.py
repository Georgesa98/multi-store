"""Store business logic: onboarding, status, opening hours."""

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils.text import slugify

from accounts.services import send_invite
from core.enums import MemberRole, Role, StoreStatus
from core.exceptions import BusinessRuleViolation, Conflict
from stores.models import OpeningHours, Store, StoreMembership

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
        send_invite(owner, store)
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
