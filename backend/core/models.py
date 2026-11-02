"""Abstract base models.

Every table gets a UUID primary key: the API contract says identifiers are
UUID strings (section 8), so this is applied uniformly rather than only on the
models the brief spelled out.
"""

import uuid

from django.db import models

from core.managers import StoreScopedManager


class TimeStampedModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ("-created_at",)


class StoreScopedModel(TimeStampedModel):
    """Anything that belongs to exactly one store and must never leak across."""

    store = models.ForeignKey(
        "stores.Store",
        on_delete=models.CASCADE,
        db_index=True,
        related_name="+",
    )

    objects = StoreScopedManager()

    class Meta:
        abstract = True
