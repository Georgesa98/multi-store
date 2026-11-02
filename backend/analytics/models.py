"""The append-only money ledger and the daily rollups insights read from."""

from decimal import Decimal

from django.db import models

from core.enums import LedgerKind, PayoutStatus
from core.models import TimeStampedModel


class LedgerEntry(TimeStampedModel):
    """Append-only. A correction is a new, compensating row.

    `gross` is what the customer paid into this line, `commission` the
    platform's cut of it, and `net` what the store (or company) keeps.
    """

    store = models.ForeignKey(
        "stores.Store",
        on_delete=models.CASCADE,
        related_name="ledger_entries",
    )
    order = models.ForeignKey(
        "orders.Order",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ledger_entries",
    )
    delivery = models.ForeignKey(
        "delivery.Delivery",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ledger_entries",
    )
    kind = models.CharField(max_length=20, choices=LedgerKind.choices)
    gross = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    commission = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    net = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))

    class Meta(TimeStampedModel.Meta):
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["store", "created_at"]),
            models.Index(fields=["order"]),
            models.Index(fields=["kind", "created_at"]),
        ]

    def __str__(self):
        return f"{self.kind} {self.gross} ({self.store_id})"


class DailyStoreStat(TimeStampedModel):
    """One row per store per reporting day, written by `rollup_day()`."""

    store = models.ForeignKey(
        "stores.Store",
        on_delete=models.CASCADE,
        related_name="daily_stats",
    )
    date = models.DateField()
    orders_placed = models.PositiveIntegerField(default=0)
    orders_delivered = models.PositiveIntegerField(default=0)
    orders_cancelled = models.PositiveIntegerField(default=0)
    new_customers = models.PositiveIntegerField(default=0)
    gross_sales = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    net_sales = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    delivery_fees = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    discounts = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    refunds = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))

    class Meta(TimeStampedModel.Meta):
        ordering = ("-date",)
        constraints = [
            models.UniqueConstraint(fields=["store", "date"], name="uniq_store_stat_per_day")
        ]
        indexes = [models.Index(fields=["store", "date"])]

    def __str__(self):
        return f"{self.store_id} {self.date}"


class DailyProductStat(TimeStampedModel):
    store = models.ForeignKey(
        "stores.Store",
        on_delete=models.CASCADE,
        related_name="product_stats",
    )
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.CASCADE,
        related_name="daily_stats",
    )
    date = models.DateField()
    qty_sold = models.PositiveIntegerField(default=0)
    revenue = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))

    class Meta(TimeStampedModel.Meta):
        ordering = ("-date",)
        constraints = [
            models.UniqueConstraint(
                fields=["store", "product", "date"], name="uniq_product_stat_per_day"
            )
        ]
        indexes = [models.Index(fields=["store", "date"])]

    def __str__(self):
        return f"{self.product_id} {self.date}: {self.qty_sold}"


class Payout(TimeStampedModel):
    """One store/company settlement for a Monday-Sunday reporting week.

    The company collected the COD cash; this row says how much of it is the
    store's, how much the company keeps as its fee, and how much the platform's
    commission is. `pending -> settled -> paid`; a paid row appends a
    `LedgerEntry(kind=payout)` so the ledger and the payout never disagree.
    """

    store = models.ForeignKey(
        "stores.Store",
        on_delete=models.CASCADE,
        related_name="payouts",
    )
    company = models.ForeignKey(
        "delivery.DeliveryCompany",
        on_delete=models.PROTECT,
        related_name="payouts",
    )
    period_start = models.DateField()
    period_end = models.DateField()
    deliveries = models.PositiveIntegerField(default=0)
    cash_collected = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    delivery_fees = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    platform_commission = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    store_net = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    company_net = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    status = models.CharField(
        max_length=20, choices=PayoutStatus.choices, default=PayoutStatus.PENDING
    )
    settled_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta(TimeStampedModel.Meta):
        ordering = ("-period_start", "store__name")
        constraints = [
            models.UniqueConstraint(
                fields=["store", "company", "period_start"],
                name="uniq_payout_per_week",
            ),
            models.CheckConstraint(
                condition=models.Q(period_end__gte=models.F("period_start")),
                name="payout_period_ordered",
            ),
        ]
        indexes = [
            models.Index(fields=["company", "status"]),
            models.Index(fields=["store", "period_start"]),
        ]

    def __str__(self):
        return f"{self.store_id}/{self.company_id} {self.period_start}"
