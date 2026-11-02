"""Notification payloads."""

from rest_framework import serializers

from notifications.models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ("id", "type", "title", "body", "data", "read_at", "created_at")
        read_only_fields = fields
