"""Celery entrypoints for notifications.

The row is already committed by the time these run; a broker outage only
delays the push, never the notification.
"""

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def send_push(notification_id):
    from notifications import push
    from notifications.models import Notification

    notification = Notification.objects.filter(pk=notification_id).select_related("user").first()
    if notification is None:
        logger.info("notification %s disappeared before its push", notification_id)
        return
    push.send(notification)
