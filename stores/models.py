from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from core.enums import MemberRole, StoreStatus
from core.models import TimeStampedModel


class Store(TimeStampedModel):
    owner = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="owned_stores",
    )
    slug = models.SlugField(max_length=80, unique=True)
    # Order-number prefix (e.g. PIZ). Set at onboarding; unique platform-wide.
    code = models.CharField(max_length=8, unique=True)
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    phone = models.CharField(max_length=32, blank=True)
    address_text = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=20, choices=StoreStatus.choices, default=StoreStatus.PENDING
    )
    logo = models.ImageField(upload_to="stores/logos/", blank=True)
    cover = models.ImageField(upload_to="stores/covers/", blank=True)
    lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    currency = models.CharField(max_length=3, default="SYP")
    commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=Decimal("0.1000"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("1"))],
    )
    is_accepting_orders = models.BooleanField(default=True)
    # Recorded addition: platform suspension requires a reason and there is
    # nowhere else to keep it until the notifications app lands.
    suspended_reason = models.TextField(blank=True)

    class Meta(TimeStampedModel.Meta):
        ordering = ("name",)
        indexes = [
            models.Index(fields=["status", "is_accepting_orders"]),
            models.Index(fields=["slug"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(commission_rate__gte=0, commission_rate__lte=1),
                name="store_commission_rate_between_0_and_1",
            )
        ]

    def __str__(self):
        return self.name

    @property
    def is_open(self) -> bool:
        """True when today's hours cover the current UTC time."""
        now = timezone.now()
        for row in self.opening_hours.all():
            if row.weekday != now.weekday() or row.is_closed:
                continue
            return row.open_time <= now.time() <= row.close_time
        return False


class StoreMembership(TimeStampedModel):
    store = models.ForeignKey(
        "stores.Store",
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    role = models.CharField(max_length=20, choices=MemberRole.choices, default=MemberRole.STAFF)
    is_active = models.BooleanField(default=True)

    class Meta(TimeStampedModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["store", "user"], name="uniq_membership_per_store")
        ]
        indexes = [
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["store", "role", "is_active"]),
        ]

    def __str__(self):
        return f"{self.user_id} @ {self.store_id} ({self.role})"

    @property
    def can_write(self) -> bool:
        return self.role in (MemberRole.OWNER, MemberRole.MANAGER)


class OpeningHours(TimeStampedModel):
    store = models.ForeignKey(
        "stores.Store",
        on_delete=models.CASCADE,
        related_name="opening_hours",
    )
    weekday = models.PositiveSmallIntegerField(help_text="0 = Monday … 6 = Sunday")
    open_time = models.TimeField()
    close_time = models.TimeField()
    is_closed = models.BooleanField(default=False)

    class Meta(TimeStampedModel.Meta):
        ordering = ("weekday",)
        constraints = [
            models.UniqueConstraint(fields=["store", "weekday"], name="uniq_hours_per_weekday"),
            models.CheckConstraint(
                condition=models.Q(weekday__gte=0, weekday__lte=6),
                name="opening_hours_weekday_range",
            ),
            models.CheckConstraint(
                condition=models.Q(is_closed=True) | models.Q(close_time__gt=models.F("open_time")),
                name="opening_hours_close_after_open",
            ),
        ]

    def __str__(self):
        return f"{self.store_id} day {self.weekday}"


class DeliveryZone(TimeStampedModel):
    store = models.ForeignKey(
        "stores.Store",
        on_delete=models.CASCADE,
        related_name="zones",
    )
    name = models.CharField(max_length=80)
    center_lat = models.DecimalField(max_digits=9, decimal_places=6)
    center_lng = models.DecimalField(max_digits=9, decimal_places=6)
    radius_km = models.DecimalField(max_digits=6, decimal_places=2)
    fee = models.DecimalField(max_digits=12, decimal_places=2)
    min_order_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    eta_minutes = models.PositiveSmallIntegerField(default=30)
    is_active = models.BooleanField(default=True)

    class Meta(TimeStampedModel.Meta):
        ordering = ("name",)
        indexes = [models.Index(fields=["store", "is_active"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(radius_km__gt=0), name="zone_radius_positive"
            ),
            models.CheckConstraint(condition=models.Q(fee__gte=0), name="zone_fee_non_negative"),
            models.CheckConstraint(
                condition=models.Q(min_order_total__gte=0),
                name="zone_min_order_non_negative",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.store_id})"
