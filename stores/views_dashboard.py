"""Store dashboard surface: own store only, staff read-only."""

from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import CourierProfile
from core.permissions import IsDashboardUser, IsDashboardWriter, ReadWritePermissionsMixin
from stores import services
from stores.models import DeliveryZone
from stores.serializers import (
    CourierInviteSerializer,
    CourierSerializer,
    DeliveryZoneSerializer,
    OpeningHoursBulkSerializer,
    OpeningHoursSerializer,
    StoreDashboardSerializer,
)


@extend_schema(tags=["dashboard"])
class StoreDetailView(ReadWritePermissionsMixin, generics.RetrieveUpdateAPIView):
    serializer_class = StoreDashboardSerializer

    def get_object(self):
        return self.request.store


@extend_schema(tags=["dashboard"])
class OpeningHoursView(ReadWritePermissionsMixin, APIView):
    @extend_schema(responses=OpeningHoursSerializer(many=True))
    def get(self, request):
        rows = request.store.opening_hours.all()
        return Response(OpeningHoursSerializer(rows, many=True).data)

    @extend_schema(request=OpeningHoursBulkSerializer, responses=OpeningHoursSerializer(many=True))
    def put(self, request):
        serializer = OpeningHoursBulkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        rows = services.replace_opening_hours(request.store, serializer.validated_data["hours"])
        return Response(OpeningHoursSerializer(rows, many=True).data)


class DashboardZoneMixin:
    serializer_class = DeliveryZoneSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return DeliveryZone.objects.none()
        return DeliveryZone.objects.filter(store=self.request.store)


@extend_schema(tags=["dashboard"])
class DeliveryZoneListCreateView(
    ReadWritePermissionsMixin, DashboardZoneMixin, generics.ListCreateAPIView
):
    def perform_create(self, serializer):
        serializer.save(store=self.request.store)


@extend_schema(tags=["dashboard"])
class DeliveryZoneDetailView(
    ReadWritePermissionsMixin, DashboardZoneMixin, generics.RetrieveUpdateDestroyAPIView
):
    def destroy(self, request, *args, **kwargs):
        # Soft delete: a zone may already be referenced by a delivery.
        zone = self.get_object()
        zone.is_active = False
        zone.save(update_fields=["is_active", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["dashboard"])
class CourierListView(generics.ListAPIView):
    permission_classes = [IsDashboardUser]
    serializer_class = CourierSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return CourierProfile.objects.none()
        return (
            CourierProfile.objects.filter(store=self.request.store)
            .select_related("user")
            .order_by("-created_at")
        )


@extend_schema(tags=["dashboard"])
class CourierInviteView(APIView):
    permission_classes = [IsDashboardWriter]

    @extend_schema(request=CourierInviteSerializer, responses={201: CourierSerializer})
    def post(self, request):
        serializer = CourierInviteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = services.invite_courier(store=request.store, **serializer.validated_data)
        profile = CourierProfile.objects.select_related("user").get(user=user)
        return Response(CourierSerializer(profile).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["dashboard"])
class CourierDetailView(APIView):
    permission_classes = [IsDashboardWriter]

    def get_object(self, request, pk):
        return generics.get_object_or_404(
            CourierProfile.objects.select_related("user"),
            pk=pk,
            store=request.store,
        )

    @extend_schema(request=CourierSerializer, responses=CourierSerializer)
    def patch(self, request, pk):
        profile = self.get_object(request, pk)
        serializer = CourierSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        if serializer.validated_data.get("is_active") is False:
            services.deactivate_courier(profile)
            profile.refresh_from_db()
        return Response(CourierSerializer(profile).data)
