"""Ledger writes at fulfilment time, and the rollups the insights read.

Money reaches the ledger exactly once per event: when an order is delivered the
goods sale and the delivery fee are written as separate rows (the platform's cut
of each differs), and a refund appends the negation of both. Nothing updates a
ledger row in place.
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Min, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from analytics.models import DailyProductStat, DailyStoreStat, LedgerEntry
from catalog.models import Product
from core.enums import (
    CompanyStatus,
    DeliveryAction,
    LedgerKind,
    OrderStatus,
    StoreStatus,
)
from core.money import money
from delivery.models import Delivery, DeliveryCompany, DeliveryEvent
from orders.models import Order, OrderItem
from stores.models import Store

ZERO = Decimal("0")
STAT_FIELDS = (
    "orders_placed",
    "orders_delivered",
    "orders_cancelled",
    "new_customers",
    "gross_sales",
    "net_sales",
    "delivery_fees",
    "discounts",
    "refunds",
)


# ---------------------------------------------------------------------------
# Reporting calendar
# ---------------------------------------------------------------------------


def report_tz() -> ZoneInfo:
    return ZoneInfo(settings.REPORT_TIME_ZONE)


def report_date() -> date:
    """Today in the reporting time zone, not UTC."""
    return timezone.now().astimezone(report_tz()).date()


def day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=report_tz())
    return start, start + timedelta(days=1)


def range_bounds(from_day: date, to_day: date) -> tuple[datetime, datetime]:
    return day_bounds(from_day)[0], day_bounds(to_day)[1]


def days_between(from_day: date, to_day: date):
    day = from_day
    while day <= to_day:
        yield day
        day += timedelta(days=1)


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


@transaction.atomic
def record_sale(order: Order) -> list[LedgerEntry]:
    """Goods sale + delivery-fee commission for a delivered order.

    Idempotent: a replay after a crash finds the sale row and writes nothing.
    """
    if LedgerEntry.objects.filter(order=order, kind=LedgerKind.SALE).exists():
        return []

    goods = money(order.subtotal - order.discount_total)
    store_commission = money(goods * order.store.commission_rate)
    rows = [
        LedgerEntry(
            store_id=order.store_id,
            order=order,
            kind=LedgerKind.SALE,
            gross=goods,
            commission=store_commission,
            net=money(goods - store_commission),
        )
    ]

    delivery = getattr(order, "delivery", None)
    if delivery is not None and order.delivery_fee > ZERO:
        rate = delivery.company.commission_rate if delivery.company_id else ZERO
        fee = money(order.delivery_fee)
        fee_commission = money(fee * rate)
        rows.append(
            LedgerEntry(
                store_id=order.store_id,
                order=order,
                delivery=delivery,
                kind=LedgerKind.COMMISSION,
                gross=fee,
                commission=fee_commission,
                net=money(fee - fee_commission),
            )
        )

    return LedgerEntry.objects.bulk_create(rows)


@transaction.atomic
def record_refund(order: Order) -> list[LedgerEntry]:
    """A refund negates every original row for the order; nothing is edited."""
    if LedgerEntry.objects.filter(order=order, kind=LedgerKind.REFUND).exists():
        return []

    originals = LedgerEntry.objects.filter(
        order=order, kind__in=(LedgerKind.SALE, LedgerKind.COMMISSION)
    )
    rows = [
        LedgerEntry(
            store_id=entry.store_id,
            order=order,
            delivery_id=entry.delivery_id,
            kind=LedgerKind.REFUND,
            gross=-entry.gross,
            commission=-entry.commission,
            net=-entry.net,
        )
        for entry in originals
    ]
    return LedgerEntry.objects.bulk_create(rows)


def record_transition(order: Order, to_status: str) -> list[LedgerEntry]:
    """Called from `orders.services.transition()` inside its transaction."""
    if to_status == OrderStatus.DELIVERED:
        return record_sale(order)
    if to_status == OrderStatus.REFUNDED:
        return record_refund(order)
    return []


# ---------------------------------------------------------------------------
# Daily figures
# ---------------------------------------------------------------------------


def _sum(queryset, field: str) -> Decimal:
    return money(queryset.aggregate(value=Sum(field))["value"] or ZERO)


def _empty_stat() -> dict:
    return {
        "orders_placed": 0,
        "orders_delivered": 0,
        "orders_cancelled": 0,
        "new_customers": 0,
        "gross_sales": ZERO,
        "net_sales": ZERO,
        "delivery_fees": ZERO,
        "discounts": ZERO,
        "refunds": ZERO,
    }


def compute_store_stat(store: Store, day: date) -> dict:
    """Live figures for one store and one reporting day."""
    start, end = day_bounds(day)
    base = Order.objects.filter(store=store)
    placed = base.filter(created_at__gte=start, created_at__lt=end)
    sold = placed.exclude(status__in=(OrderStatus.CANCELLED, OrderStatus.REFUNDED))
    delivered = base.filter(delivered_at__gte=start, delivered_at__lt=end)
    cancelled = base.filter(cancelled_at__gte=start, cancelled_at__lt=end)

    refunded_rows = LedgerEntry.objects.filter(
        store=store,
        kind=LedgerKind.REFUND,
        created_at__gte=start,
        created_at__lt=end,
    )
    refunds = -_sum(refunded_rows, "gross")

    gross_sales = _sum(sold, "subtotal")
    discounts = _sum(sold, "discount_total")

    first_orders = base.values("customer_id").annotate(first_at=Min("created_at"))
    new_customers = first_orders.filter(first_at__gte=start, first_at__lt=end).count()

    stats = {
        "orders_placed": placed.count(),
        "orders_delivered": delivered.count(),
        "orders_cancelled": cancelled.count(),
        "new_customers": new_customers,
        "gross_sales": gross_sales,
        "net_sales": money(gross_sales - discounts - refunds),
        "delivery_fees": _sum(sold, "delivery_fee"),
        "discounts": discounts,
        "refunds": money(refunds),
    }
    return stats


def compute_product_stats(store: Store, day: date) -> list[dict]:
    start, end = day_bounds(day)
    rows = (
        OrderItem.objects.filter(
            order__store=store,
            order__created_at__gte=start,
            order__created_at__lt=end,
            product__isnull=False,
        )
        .exclude(order__status__in=(OrderStatus.CANCELLED, OrderStatus.REFUNDED))
        .values("product_id")
        .annotate(qty_sold=Sum("quantity"), revenue=Sum("line_total"))
    )
    return [
        {
            "product_id": row["product_id"],
            "qty_sold": row["qty_sold"] or 0,
            "revenue": money(row["revenue"] or ZERO),
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Rollups
# ---------------------------------------------------------------------------


@transaction.atomic
def rollup_day(day: date) -> int:
    """Recompute one reporting day from current state. Returns stores touched."""
    start, end = day_bounds(day)
    store_ids = set(
        Order.objects.filter(
            created_at__gte=start,
            created_at__lt=end,
        ).values_list("store_id", flat=True)
    )
    store_ids |= set(
        Order.objects.filter(delivered_at__gte=start, delivered_at__lt=end).values_list(
            "store_id", flat=True
        )
    )
    store_ids |= set(
        Order.objects.filter(cancelled_at__gte=start, cancelled_at__lt=end).values_list(
            "store_id", flat=True
        )
    )
    store_ids |= set(
        LedgerEntry.objects.filter(
            kind=LedgerKind.REFUND, created_at__gte=start, created_at__lt=end
        ).values_list("store_id", flat=True)
    )

    for store in Store.objects.filter(pk__in=store_ids):
        DailyStoreStat.objects.update_or_create(
            store=store, date=day, defaults=compute_store_stat(store, day)
        )
        DailyProductStat.objects.filter(store=store, date=day).delete()
        DailyProductStat.objects.bulk_create(
            [
                DailyProductStat(
                    store=store,
                    product_id=row["product_id"],
                    date=day,
                    qty_sold=row["qty_sold"],
                    revenue=row["revenue"],
                )
                for row in compute_product_stats(store, day)
            ]
        )
    return len(store_ids)


def rollup_range(from_day: date, to_day: date) -> int:
    return sum(rollup_day(day) for day in days_between(from_day, to_day))


# ---------------------------------------------------------------------------
# Insight reads: rollups for past days, live for today
# ---------------------------------------------------------------------------


def store_day(store: Store, day: date) -> dict:
    if day == report_date():
        return compute_store_stat(store, day)
    row = DailyStoreStat.objects.filter(store=store, date=day).first()
    if row is None:
        return _empty_stat()
    return {field: getattr(row, field) for field in STAT_FIELDS}


def store_series(store: Store, from_day: date, to_day: date) -> list[dict]:
    return [{"date": day, **store_day(store, day)} for day in days_between(from_day, to_day)]


def store_summary(store: Store, from_day: date, to_day: date) -> dict:
    series = store_series(store, from_day, to_day)
    totals = {field: sum(row[field] for row in series) for field in STAT_FIELDS}
    totals = {
        field: money(value) if isinstance(value, Decimal) else value
        for field, value in totals.items()
    }
    orders = totals["orders_placed"]
    return {
        "from_date": from_day,
        "to_date": to_day,
        "orders": orders,
        "orders_delivered": totals["orders_delivered"],
        "orders_cancelled": totals["orders_cancelled"],
        "new_customers": totals["new_customers"],
        "gross_sales": totals["gross_sales"],
        "net_sales": totals["net_sales"],
        "delivery_fees": totals["delivery_fees"],
        "discounts": totals["discounts"],
        "refunds": totals["refunds"],
        "aov": money(totals["gross_sales"] / orders) if orders else ZERO,
    }


def product_totals(store: Store, from_day: date, to_day: date) -> list[dict]:
    totals: dict = {}
    for day in days_between(from_day, to_day):
        if day == report_date():
            rows = compute_product_stats(store, day)
        else:
            rows = DailyProductStat.objects.filter(store=store, date=day).values(
                "product_id", "qty_sold", "revenue"
            )
        for row in rows:
            bucket = totals.setdefault(row["product_id"], {"qty_sold": 0, "revenue": ZERO})
            bucket["qty_sold"] += row["qty_sold"]
            bucket["revenue"] += row["revenue"]

    names = dict(Product.objects.filter(pk__in=totals).values_list("id", "name"))
    products = [
        {
            "product_id": product_id,
            "name": names.get(product_id, ""),
            "qty_sold": bucket["qty_sold"],
            "revenue": money(bucket["revenue"]),
        }
        for product_id, bucket in totals.items()
    ]
    return sorted(products, key=lambda row: (-row["qty_sold"], -row["revenue"]))


def orders_by_status(store: Store, from_day: date, to_day: date) -> list[dict]:
    start, end = range_bounds(from_day, to_day)
    rows = (
        Order.objects.filter(store=store, created_at__gte=start, created_at__lt=end)
        .values("status")
        .annotate(count=Count("id"))
    )
    found = {row["status"]: row["count"] for row in rows}
    return [{"status": status, "count": found.get(status, 0)} for status in OrderStatus.values]


def delivery_performance(store: Store, from_day: date, to_day: date) -> dict:
    start, end = range_bounds(from_day, to_day)
    delivered = Delivery.objects.filter(store=store, delivered_at__gte=start, delivered_at__lt=end)
    durations = []
    for delivery in delivered:
        started = delivery.accepted_at or delivery.requested_at
        if started and delivery.delivered_at:
            elapsed = (delivery.delivered_at - started).total_seconds()
            durations.append(Decimal(str(elapsed)) / Decimal(60))

    failed = DeliveryEvent.objects.filter(
        delivery__store=store,
        action=DeliveryAction.FAILED,
        created_at__gte=start,
        created_at__lt=end,
    ).count()
    completed = delivered.count()
    attempts = completed + failed
    avg_minutes = money(sum(durations) / len(durations)) if durations else ZERO
    failure_rate = (
        (Decimal(failed) / Decimal(attempts)).quantize(Decimal("0.0001")) if attempts else ZERO
    )
    return {
        "completed": completed,
        "failed": failed,
        "avg_minutes": avg_minutes,
        "failure_rate": failure_rate,
    }


# ---------------------------------------------------------------------------
# Platform-wide views (ledger is already the source of truth)
# ---------------------------------------------------------------------------


def platform_overview(from_day: date, to_day: date) -> dict:
    start, end = range_bounds(from_day, to_day)
    orders = Order.objects.filter(created_at__gte=start, created_at__lt=end)
    return {
        "from_date": from_day,
        "to_date": to_day,
        "orders": orders.count(),
        "gmv": money(orders.aggregate(value=Sum("total"))["value"] or ZERO),
        "active_stores": Store.objects.filter(status=StoreStatus.ACTIVE).count(),
        "active_companies": DeliveryCompany.objects.filter(status=CompanyStatus.ACTIVE).count(),
    }


def platform_revenue(from_day: date, to_day: date) -> list[dict]:
    start, end = range_bounds(from_day, to_day)
    rows = (
        LedgerEntry.objects.filter(created_at__gte=start, created_at__lt=end)
        .annotate(day=TruncDate("created_at", tzinfo=report_tz()))
        .values("day")
        .annotate(gross=Sum("gross"), commission=Sum("commission"), net=Sum("net"))
        .order_by("day")
    )
    found = {row["day"]: row for row in rows}
    series = []
    for day in days_between(from_day, to_day):
        row = found.get(day, {})
        series.append(
            {
                "date": day,
                "gross": money(row.get("gross") or ZERO),
                "commission": money(row.get("commission") or ZERO),
                "net": money(row.get("net") or ZERO),
            }
        )
    return series


def ledger_for_store(store: Store):
    return LedgerEntry.objects.filter(store=store).select_related("order", "delivery")
