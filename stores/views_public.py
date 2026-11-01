"""Public store browsing: no authentication required."""

from django.db.models import Prefetch
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from core.enums import StoreStatus
from core.exceptions import BusinessRuleViolation
from core.geo import haversine_km
from stores import services
from stores.models import DeliveryZone, OpeningHours, Store
from stores.serializers import (
    DeliveryQuoteSerializer,
    StorePublicDetailSerializer,
    StorePublicSerializer,
)


def _visible_stores():
    return (
        Store.objects.filter(status=StoreStatus.ACTIVE)
        .prefetch_related(
            Prefetch("opening_hours", queryset=OpeningHours.objects.order_by("weekday"))
        )
        .order_by("name")
    )


@extend_schema(tags=["public"])
class PublicStoreListView(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = StorePublicSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter("q", str, description="Search name and description"),
            OpenApiParameter("lat", float, description="Customer latitude"),
            OpenApiParameter("lng", float, description="Customer longitude"),
            OpenApiParameter("radius", float, description="Radius in kilometres"),
            OpenApiParameter("is_open", bool, description="Only stores open right now"),
        ]
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Store.objects.none()
        qs = list(_visible_stores())
        params = self.request.query_params

        q = params.get("q")
        if q:
            qs = [
                s for s in qs if q.lower() in s.name.lower() or q.lower() in s.description.lower()
            ]

        lat, lng = params.get("lat"), params.get("lng")
        if lat is not None and lng is not None:
            radius = float(params.get("radius") or 10)
            qs = [
                s
                for s in qs
                if s.lat is not None
                and s.lng is not None
                and haversine_km(lat, lng, s.lat, s.lng) <= radius
            ]

        if params.get("is_open") in ("true", "1", "True"):
            qs = [s for s in qs if s.is_open and s.is_accepting_orders]

        return qs


@extend_schema(tags=["public"])
class PublicStoreDetailView(generics.RetrieveAPIView):
    permission_classes = [AllowAny]
    serializer_class = StorePublicDetailSerializer
    lookup_field = "slug"

    def get_queryset(self):
        return Store.objects.filter(status=StoreStatus.ACTIVE).prefetch_related(
            Prefetch("opening_hours", queryset=OpeningHours.objects.order_by("weekday")),
            Prefetch("zones", queryset=DeliveryZone.objects.filter(is_active=True)),
        )


@extend_schema(tags=["public"])
class DeliveryQuoteView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(request=DeliveryQuoteSerializer, responses=dict)
    def post(self, request, slug):
        serializer = DeliveryQuoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        store = generics.get_object_or_404(Store, slug=slug, status=StoreStatus.ACTIVE)
        zone = services.zone_for_point(
            store,
            serializer.validated_data["lat"],
            serializer.validated_data["lng"],
        )
        if zone is None:
            raise BusinessRuleViolation({"detail": "This address is outside every delivery zone."})
        return Response(
            {
                "zone_id": str(zone.id),
                "zone_name": zone.name,
                "fee": f"{zone.fee:.2f}",
                "min_order_total": f"{zone.min_order_total:.2f}",
                "eta_minutes": zone.eta_minutes,
                "currency": store.currency,
            },
            status=status.HTTP_200_OK,
        )
