"""Platform insights: GMV, the platform's commission series and every ledger row."""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from analytics import services
from analytics.models import LedgerEntry
from analytics.serializers import (
    LedgerEntrySerializer,
    PlatformOverviewSerializer,
    PlatformRevenueSerializer,
)
from analytics.views_dashboard import day_range, range_parameters
from core.permissions import IsSuperAdmin


@extend_schema(tags=["platform"])
class PlatformOverviewView(APIView):
    permission_classes = [IsSuperAdmin]

    @extend_schema(parameters=range_parameters(), responses=PlatformOverviewSerializer)
    def get(self, request):
        data = services.platform_overview(*day_range(request))
        return Response(PlatformOverviewSerializer(data).data)


@extend_schema(tags=["platform"])
class PlatformRevenueView(APIView):
    permission_classes = [IsSuperAdmin]

    @extend_schema(parameters=range_parameters(), responses=PlatformRevenueSerializer(many=True))
    def get(self, request):
        data = services.platform_revenue(*day_range(request))
        return Response(PlatformRevenueSerializer(data, many=True).data)


@extend_schema(tags=["platform"])
class PlatformLedgerView(generics.ListAPIView):
    """Every store's ledger rows, filterable by store."""

    permission_classes = [IsSuperAdmin]
    serializer_class = LedgerEntrySerializer

    @extend_schema(
        parameters=range_parameters()
        + [
            OpenApiParameter("store", str, description="Store UUID"),
            OpenApiParameter("kind", str, description="sale, refund, commission, payout"),
        ]
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return LedgerEntry.objects.none()
        queryset = LedgerEntry.objects.select_related("order", "delivery")
        params = self.request.query_params
        if store := params.get("store"):
            queryset = queryset.filter(store_id=store)
        if kind := params.get("kind"):
            queryset = queryset.filter(kind=kind)
        from_day, to_day = day_range(self.request)
        start, end = services.range_bounds(from_day, to_day)
        return queryset.filter(created_at__gte=start, created_at__lt=end)
