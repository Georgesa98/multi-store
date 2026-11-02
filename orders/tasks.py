"""Scheduled order upkeep.

`cancel_stale_pending_orders` is the only place an order is cancelled without a
person asking: a store that never confirms releases the stock it reserved.
"""

import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from core.enums import OrderStatus
from core.exceptions import Conflict, InvalidTransition
from orders import services
from orders.models import Order

logger = logging.getLogger(__name__)

STALE_AFTER_MINUTES = 30


@shared_task
def cancel_stale_pending_orders(older_than_minutes=STALE_AFTER_MINUTES):
    """Cancel `pending` orders nobody confirmed, restoring their stock."""
    cutoff = timezone.now() - timedelta(minutes=int(older_than_minutes))
    stale_ids = list(
        Order.objects.filter(status=OrderStatus.PENDING, created_at__lt=cutoff).values_list(
            "id", flat=True
        )
    )

    cancelled = 0
    for order_id in stale_ids:
        order = Order.objects.filter(pk=order_id).first()
        if order is None or order.status != OrderStatus.PENDING:
            continue
        try:
            services.transition(
                order=order,
                to_status=OrderStatus.CANCELLED,
                actor=services.SYSTEM,
                note=f"Cancelled automatically: the store did not confirm within "
                f"{int(older_than_minutes)} minutes.",
            )
        except (Conflict, InvalidTransition) as exc:
            # Another worker, or the store, got there first; nothing to do.
            logger.info("skipping stale order %s: %s", order_id, exc)
            continue
        cancelled += 1

    logger.info("cancelled %d stale pending order(s)", cancelled)
    return cancelled
