"""Celery entrypoints for analytics."""

import logging
from datetime import date, timedelta

from celery import shared_task

from analytics import services

logger = logging.getLogger(__name__)


@shared_task
def rollup_daily_stats(day=None):
    """Default target: yesterday in the reporting time zone."""
    target = date.fromisoformat(day) if day else services.report_date() - timedelta(days=1)
    stores = services.rollup_day(target)
    logger.info("rolled up %s for %d store(s)", target, stores)
    return stores


@shared_task
def write_ledger_for_delivered(order_id):
    """Safety net for the synchronous write inside `transition()`."""
    from core.enums import OrderStatus
    from orders.models import Order

    order = Order.objects.select_related("store", "delivery__company").filter(pk=order_id).first()
    if order is None or order.status != OrderStatus.DELIVERED:
        return 0
    return len(services.record_sale(order))


@shared_task
def materialise_payouts(period_start=None):
    """Weekly settlement rows; defaults to the week that just ended."""
    target = date.fromisoformat(period_start) if period_start else None
    payouts = services.materialise_payouts(target)
    logger.info("materialised %d payout(s)", len(payouts))
    return len(payouts)
