"""One row per thing a user should see. Push only mirrors it."""

from django.conf import settings
from django.db import models

from core.enums import NotificationType
from core.models import TimeStampedModel


class Notification(TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    type = models.CharField(
        max_length=20,
        choices=NotificationType.choices,
        default=NotificationType.SYSTEM,
    )
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    data = models.JSONField(default=dict, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta(TimeStampedModel.Meta):
        indexes = [
            models.Index(fields=["user", "read_at"], name="notif_user_read_idx"),
        ]

    def __str__(self):
        return f"{self.user_id}: {self.title}"
