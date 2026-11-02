"""The user's own notification inbox. Any authenticated role has one."""

from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from notifications.models import Notification
from notifications.serializers import NotificationSerializer


@extend_schema(tags=["notifications"])
class NotificationListView(generics.ListAPIView):
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[OpenApiParameter("unread", bool, description="Only unread rows")],
        responses=NotificationSerializer(many=True),
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Notification.objects.none()
        queryset = Notification.objects.filter(user=self.request.user)
        if self.request.query_params.get("unread") in ("true", "1", "True"):
            queryset = queryset.filter(read_at__isnull=True)
        return queryset


@extend_schema(tags=["notifications"])
class NotificationReadView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses=NotificationSerializer)
    def post(self, request, pk):
        notification = get_object_or_404(Notification, pk=pk, user=request.user)
        if notification.read_at is None:
            notification.read_at = timezone.now()
            notification.save(update_fields=["read_at", "updated_at"])
        return Response(NotificationSerializer(notification).data)


@extend_schema(tags=["notifications"])
class NotificationReadAllView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: None})
    def post(self, request):
        updated = Notification.objects.filter(user=request.user, read_at__isnull=True).update(
            read_at=timezone.now()
        )
        return Response({"updated": updated}, status=status.HTTP_200_OK)
