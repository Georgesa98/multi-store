"""Fan-out for live tracking: HTTP writes, socket reads.

Broadcasts are best effort. A tracking hiccup must never roll back the order,
so the layer call is wrapped and logged rather than raised.
"""

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

LOCATION_THROTTLE_SECONDS = 1


def group_for(delivery_id) -> str:
    return f"delivery_{delivery_id}"


def _send(delivery_id, message) -> None:
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(group_for(delivery_id), message)
    except Exception:
        logger.warning("tracking broadcast failed for delivery %s", delivery_id, exc_info=True)


def broadcast_location(delivery_id, *, lat, lng) -> None:
    """One frame per second at most; the trail keeps its own 60 s sampling."""
    if not cache.add(f"tracking:location:{delivery_id}", 1, timeout=LOCATION_THROTTLE_SECONDS):
        return
    _send(
        delivery_id,
        {
            "type": "location",
            "lat": float(lat),
            "lng": float(lng),
            "at": timezone.now().isoformat(),
        },
    )


def broadcast_status(delivery) -> None:
    _send(
        delivery.id,
        {
            "type": "status",
            "status": delivery.status,
            "at": timezone.now().isoformat(),
        },
    )
