"""Scheduled delivery upkeep.

The live position lives on `CourierLocation` (one row per courier); the trail on
`DeliveryLocationPing` only exists to replay a trip, so it expires.
"""

import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from delivery.models import DeliveryLocationPing

logger = logging.getLogger(__name__)

PING_RETENTION_DAYS = 30


@shared_task
def prune_location_pings(retention_days=PING_RETENTION_DAYS):
    cutoff = timezone.now() - timedelta(days=int(retention_days))
    deleted, _ = DeliveryLocationPing.objects.filter(created_at__lt=cutoff).delete()
    logger.info("pruned %d location ping(s)", deleted)
    return deleted
