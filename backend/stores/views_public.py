"""Public store browsing: no authentication required."""

from django.db.models import Prefetch, Q
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from core.cache import PublicCacheMixin
from core.enums import StoreStatus
from core.exceptions import BusinessRuleViolation
from core.geo import distance_km_expression
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


def _truthy(value) -> bool:
    return value in ("true", "1", "True")


def _float_param(params, name, default=None):
    raw = params.get(name)
    if raw in (None, ""):
        if default is None:
            raise ValidationError({name: ["This query parameter is required."]})
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        raise ValidationError({name: ["Must be a number."]}) from None


@extend_schema(tags=["public"])
class PublicStoreListView(PublicCacheMixin, generics.ListAPIView):
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

        # A queryset, not a list: the global OrderingFilter needs `.model`, and
        # pagination must slice in the database. Returning a list here made
        # `?ordering=` a 500 and filtered every store per request.
        qs = _visible_stores()
        params = self.request.query_params

        if q := params.get("q"):
            qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q))

        if _truthy(params.get("is_open")):
            now = timezone.now()
            qs = qs.filter(
                is_accepting_orders=True,
                opening_hours__weekday=now.weekday(),
                opening_hours__is_closed=False,
                opening_hours__open_time__lte=now.time(),
                opening_hours__close_time__gte=now.time(),
            )

        if params.get("lat") is not None and params.get("lng") is not None:
            lat = _float_param(params, "lat")
            lng = _float_param(params, "lng")
            radius = _float_param(params, "radius", default=10.0)
            qs = (
                qs.filter(lat__isnull=False, lng__isnull=False)
                .annotate(distance_km=distance_km_expression(lat, lng))
                .filter(distance_km__lte=radius)
            )

        return qs


@extend_schema(tags=["public"])
class PublicStoreDetailView(PublicCacheMixin, generics.RetrieveAPIView):
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
