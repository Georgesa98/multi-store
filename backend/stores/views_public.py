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
from core.throttling import ScopedThrottleMixin
from delivery.services import quote_for_store
from stores.models import OpeningHours, Store
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
            "delivery_partners__company",
        )


@extend_schema(tags=["public"])
class DeliveryQuoteView(ScopedThrottleMixin, APIView):
    permission_classes = [AllowAny]
    throttle_scope = "quote"

    @extend_schema(request=DeliveryQuoteSerializer, responses=dict)
    def post(self, request, slug):
        serializer = DeliveryQuoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        store = generics.get_object_or_404(Store, slug=slug, status=StoreStatus.ACTIVE)
        quote = quote_for_store(
            store,
            serializer.validated_data["lat"],
            serializer.validated_data["lng"],
        )
        if quote is None:
            raise BusinessRuleViolation(
                {"detail": "No delivery company covers this address for this store."}
            )
        company, zone = quote
        return Response(
            {
                "company_id": str(company.id),
                "company_name": company.name,
                "zone_id": str(zone.id),
                "zone_name": zone.name,
                "fee": f"{zone.fee:.2f}",
                "min_order_total": f"{zone.min_order_total:.2f}",
                "eta_minutes": zone.eta_minutes,
                "currency": store.currency,
            },
            status=status.HTTP_200_OK,
        )
