"""Checkout groups, orders, their immutable snapshots, and coupons."""

import uuid
from decimal import Decimal

from django.db import models

from core.enums import CouponType, OrderStatus, PaymentStatus
from core.models import StoreScopedModel, TimeStampedModel


class CheckoutGroup(TimeStampedModel):
    """One checkout action; produces one order per store."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="checkout_groups",
    )
    address_snapshot = models.JSONField(default=dict)
    idempotency_key = models.CharField(max_length=128, unique=True, null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta(TimeStampedModel.Meta):
        indexes = [models.Index(fields=["customer", "created_at"])]

    def __str__(self):
        return f"Checkout {self.id}"


class Order(StoreScopedModel):
    group = models.ForeignKey(
        "orders.CheckoutGroup",
        on_delete=models.CASCADE,
        related_name="orders",
    )
    customer = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="orders",
    )
    number = models.CharField(max_length=32)
    status = models.CharField(
        max_length=20, choices=OrderStatus.choices, default=OrderStatus.PENDING
    )
    payment_method = models.CharField(max_length=20, default="cod")
    payment_status = models.CharField(
        max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID
    )
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    delivery_fee = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    discount_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    tax_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    currency = models.CharField(max_length=3, default="SYP")
    address_snapshot = models.JSONField(default=dict)
    customer_note = models.TextField(blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.TextField(blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta(StoreScopedModel.Meta):
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(fields=["store", "number"], name="uniq_order_number"),
            models.CheckConstraint(condition=models.Q(total__gte=0), name="order_total_gte_0"),
            models.CheckConstraint(
                condition=models.Q(
                    total=models.F("subtotal")
                    + models.F("delivery_fee")
                    + models.F("tax_total")
                    - models.F("discount_total")
                ),
                name="order_total_matches_parts",
            ),
        ]
        indexes = [
            models.Index(fields=["store", "status"]),
            models.Index(fields=["store", "created_at"]),
            models.Index(fields=["customer", "created_at"]),
        ]

    def __str__(self):
        return self.number


class OrderItem(TimeStampedModel):
    """Snapshot fields are written once and never updated."""

    order = models.ForeignKey(
        "orders.Order",
        on_delete=models.CASCADE,
        related_name="items",
    )
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    variant = models.ForeignKey(
        "catalog.ProductVariant",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    name_snapshot = models.CharField(max_length=200)
    variant_label_snapshot = models.CharField(max_length=60, blank=True)
    image_url_snapshot = models.CharField(max_length=500, blank=True)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    quantity = models.PositiveIntegerField()
    line_total = models.DecimalField(max_digits=12, decimal_places=2)
    options_snapshot = models.JSONField(default=dict, blank=True)

    class Meta(TimeStampedModel.Meta):
        ordering = ("created_at",)
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="order_item_quantity_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(line_total=models.F("unit_price") * models.F("quantity")),
                name="order_item_line_total_matches",
            ),
        ]
        indexes = [models.Index(fields=["order"])]

    def __str__(self):
        return f"{self.quantity} x {self.name_snapshot}"


class OrderStatusEvent(TimeStampedModel):
    order = models.ForeignKey(
        "orders.Order",
        on_delete=models.CASCADE,
        related_name="events",
    )
    from_status = models.CharField(max_length=20, choices=OrderStatus.choices, blank=True)
    to_status = models.CharField(max_length=20, choices=OrderStatus.choices)
    actor = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    actor_role = models.CharField(max_length=20, blank=True)
    note = models.TextField(blank=True)

    class Meta(TimeStampedModel.Meta):
        ordering = ("created_at",)
        indexes = [models.Index(fields=["order", "created_at"])]

    def __str__(self):
        return f"{self.from_status or 'new'} -> {self.to_status}"


class OrderSequence(TimeStampedModel):
    """Per-store counter; locked with select_for_update() to allocate numbers."""

    store = models.OneToOneField(
        "stores.Store",
        on_delete=models.CASCADE,
        related_name="order_sequence",
    )
    last_number = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.store_id}: {self.last_number}"


class Coupon(TimeStampedModel):
    store = models.ForeignKey(
        "stores.Store",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="coupons",
    )
    code = models.CharField(max_length=40)
    discount_type = models.CharField(max_length=20, choices=CouponType.choices)
    value = models.DecimalField(max_digits=12, decimal_places=2)
    min_order_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    max_discount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    max_uses = models.PositiveIntegerField(null=True, blank=True)
    used_count = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta(TimeStampedModel.Meta):
        ordering = ("code",)
        constraints = [
            # Postgres treats NULLs as distinct, so `unique(store, code)` alone
            # would allow duplicate platform-wide coupons. Two partial uniques.
            models.UniqueConstraint(
                fields=["store", "code"],
                condition=models.Q(store__isnull=False),
                name="uniq_coupon_per_store",
            ),
            models.UniqueConstraint(
                fields=["code"],
                condition=models.Q(store__isnull=True),
                name="uniq_coupon_platform",
            ),
            models.CheckConstraint(condition=models.Q(value__gte=0), name="coupon_value_gte_0"),
        ]
        indexes = [models.Index(fields=["store", "is_active"])]

    def __str__(self):
        return self.code


class CouponRedemption(TimeStampedModel):
    coupon = models.ForeignKey(
        "orders.Coupon",
        on_delete=models.PROTECT,
        related_name="redemptions",
    )
    customer = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="coupon_redemptions",
    )
    order = models.ForeignKey(
        "orders.Order",
        on_delete=models.CASCADE,
        related_name="coupon_redemptions",
    )
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta(TimeStampedModel.Meta):
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["coupon", "order"], name="uniq_coupon_redemption_per_order"
            )
        ]
        indexes = [models.Index(fields=["customer"])]

    def __str__(self):
        return f"{self.coupon_id} -> {self.order_id}"
