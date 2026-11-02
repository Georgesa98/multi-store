"""Delivery companies, their zones and couriers, and per-order fulfilment."""

from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from core.enums import CompanyStatus, DeliveryStatus, MemberRole
from core.models import StoreScopedModel, TimeStampedModel


class DeliveryCompany(TimeStampedModel):
    """A third-party fleet. Couriers belong here, never to a store."""

    owner = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="owned_delivery_companies",
    )
    slug = models.SlugField(max_length=80, unique=True)
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    phone = models.CharField(max_length=32, blank=True)
    address_text = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=20, choices=CompanyStatus.choices, default=CompanyStatus.PENDING
    )
    logo = models.ImageField(upload_to="companies/logos/", blank=True)
    cover = models.ImageField(upload_to="companies/covers/", blank=True)
    lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    # The platform's cut of the delivery fee the company keeps.
    commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=Decimal("0.1000"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("1"))],
    )
    is_accepting_jobs = models.BooleanField(default=True)
    suspended_reason = models.TextField(blank=True)

    class Meta(TimeStampedModel.Meta):
        ordering = ("name",)
        verbose_name_plural = "delivery companies"
        indexes = [
            models.Index(fields=["status", "is_accepting_jobs"]),
            models.Index(fields=["slug"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(commission_rate__gte=0, commission_rate__lte=1),
                name="company_commission_rate_between_0_and_1",
            )
        ]

    def __str__(self):
        return self.name


class CompanyMembership(TimeStampedModel):
    company = models.ForeignKey(
        "delivery.DeliveryCompany",
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="company_memberships",
    )
    role = models.CharField(max_length=20, choices=MemberRole.choices, default=MemberRole.STAFF)
    is_active = models.BooleanField(default=True)

    class Meta(TimeStampedModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["company", "user"], name="uniq_membership_per_company")
        ]
        indexes = [
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["company", "role", "is_active"]),
        ]

    def __str__(self):
        return f"{self.user_id} @ {self.company_id} ({self.role})"

    @property
    def can_write(self) -> bool:
        return self.role in (MemberRole.OWNER, MemberRole.MANAGER)


class StoreDeliveryPartner(TimeStampedModel):
    """A store's contract with a company, ordered by `priority` (lower first)."""

    store = models.ForeignKey(
        "stores.Store",
        on_delete=models.CASCADE,
        related_name="delivery_partners",
    )
    company = models.ForeignKey(
        "delivery.DeliveryCompany",
        on_delete=models.CASCADE,
        related_name="store_links",
    )
    priority = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta(TimeStampedModel.Meta):
        ordering = ("priority", "created_at")
        constraints = [
            models.UniqueConstraint(fields=["store", "company"], name="uniq_partner_per_store")
        ]
        indexes = [
            models.Index(fields=["store", "is_active", "priority"]),
            models.Index(fields=["company", "is_active"]),
        ]

    def __str__(self):
        return f"{self.store_id} -> {self.company_id}"


class DeliveryZone(TimeStampedModel):
    """Company-owned coverage circle; fee, eta and minimum are the company's terms."""

    company = models.ForeignKey(
        "delivery.DeliveryCompany",
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
        constraints = [
            models.UniqueConstraint(fields=["company", "name"], name="uniq_zone_name_per_company"),
            models.CheckConstraint(
                condition=models.Q(radius_km__gt=0), name="zone_radius_positive"
            ),
            models.CheckConstraint(condition=models.Q(fee__gte=0), name="zone_fee_non_negative"),
            models.CheckConstraint(
                condition=models.Q(min_order_total__gte=0),
                name="zone_min_order_non_negative",
            ),
        ]
        indexes = [models.Index(fields=["company", "is_active"])]

    def __str__(self):
        return f"{self.name} ({self.company_id})"


class Delivery(StoreScopedModel):
    """One fulfilment per order, owned operationally by a delivery company."""

    order = models.OneToOneField(
        "orders.Order",
        on_delete=models.CASCADE,
        related_name="delivery",
    )
    company = models.ForeignKey(
        "delivery.DeliveryCompany",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="deliveries",
    )
    courier = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deliveries",
    )
    zone = models.ForeignKey(
        "delivery.DeliveryZone",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deliveries",
    )
    status = models.CharField(
        max_length=20, choices=DeliveryStatus.choices, default=DeliveryStatus.UNASSIGNED
    )
    assign_attempts = models.PositiveSmallIntegerField(default=0)
    requested_at = models.DateTimeField(null=True, blank=True)
    offered_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    picked_up_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    distance_km = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    fee = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    cash_to_collect = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    cash_collected = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    cash_collected_at = models.DateTimeField(null=True, blank=True)
    proof_photo = models.ImageField(upload_to="delivery/proofs/", blank=True)
    proof_otp = models.CharField(max_length=12, blank=True)
    proof_note = models.TextField(blank=True)
    failure_reason = models.TextField(blank=True)

    class Meta(StoreScopedModel.Meta):
        ordering = ("-created_at",)
        verbose_name_plural = "deliveries"
        indexes = [
            models.Index(fields=["store", "status"]),
            models.Index(fields=["company", "status"]),
            models.Index(fields=["courier", "status"]),
            models.Index(fields=["status", "offered_at"]),
        ]

    def __str__(self):
        return f"Delivery {self.order_id} ({self.status})"


class DeliveryEvent(TimeStampedModel):
    delivery = models.ForeignKey(
        "delivery.Delivery",
        on_delete=models.CASCADE,
        related_name="events",
    )
    from_courier = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    to_courier = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    from_company = models.ForeignKey(
        "delivery.DeliveryCompany",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    to_company = models.ForeignKey(
        "delivery.DeliveryCompany",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    action = models.CharField(max_length=40)
    actor = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    note = models.TextField(blank=True)

    class Meta(TimeStampedModel.Meta):
        ordering = ("created_at",)
        indexes = [models.Index(fields=["delivery", "created_at"])]

    def __str__(self):
        return f"{self.action} ({self.delivery_id})"


class CourierLocation(TimeStampedModel):
    """Latest known position only; the trail lives in `DeliveryLocationPing`."""

    courier = models.OneToOneField(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="courier_location",
    )
    lat = models.DecimalField(max_digits=9, decimal_places=6)
    lng = models.DecimalField(max_digits=9, decimal_places=6)
    accuracy_m = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    heading = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    is_online = models.BooleanField(default=False)

    class Meta(TimeStampedModel.Meta):
        indexes = [models.Index(fields=["is_online"])]

    def __str__(self):
        return f"{self.courier_id}: {self.lat},{self.lng}"


class DeliveryLocationPing(TimeStampedModel):
    """Sampled trail, at most one row per minute per delivery."""

    delivery = models.ForeignKey(
        "delivery.Delivery",
        on_delete=models.CASCADE,
        related_name="location_pings",
    )
    lat = models.DecimalField(max_digits=9, decimal_places=6)
    lng = models.DecimalField(max_digits=9, decimal_places=6)

    class Meta(TimeStampedModel.Meta):
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["delivery", "created_at"])]

    def __str__(self):
        return f"{self.delivery_id}: {self.lat},{self.lng}"
