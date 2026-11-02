"""Platform insights: GMV, the platform's commission series and every ledger row."""

from django.utils.dateparse import parse_date
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from analytics import services
from analytics.models import LedgerEntry, Payout
from analytics.serializers import (
    LedgerEntrySerializer,
    PayoutSerializer,
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


@extend_schema(tags=["platform"])
class PlatformPayoutListView(generics.ListAPIView):
    """Weekly store/company settlements, filterable by scope and status."""

    permission_classes = [IsSuperAdmin]
    serializer_class = PayoutSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter("store", str, description="Store UUID"),
            OpenApiParameter("company", str, description="Delivery company UUID"),
            OpenApiParameter("status", str, description="pending, settled, paid"),
            OpenApiParameter("from", str, description="ISO date on period_start"),
            OpenApiParameter("to", str, description="ISO date on period_start"),
        ]
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Payout.objects.none()
        queryset = Payout.objects.select_related("store", "company")
        params = self.request.query_params
        if store := params.get("store"):
            queryset = queryset.filter(store_id=store)
        if company := params.get("company"):
            queryset = queryset.filter(company_id=company)
        if status := params.get("status"):
            queryset = queryset.filter(status=status)
        if from_day := parse_date(params.get("from", "")):
            queryset = queryset.filter(period_start__gte=from_day)
        if to_day := parse_date(params.get("to", "")):
            queryset = queryset.filter(period_start__lte=to_day)
        return queryset


@extend_schema(tags=["platform"])
class PlatformPayoutSettleView(APIView):
    permission_classes = [IsSuperAdmin]

    @extend_schema(request=None, responses=PayoutSerializer)
    def post(self, request, pk):
        payout = generics.get_object_or_404(Payout, pk=pk)
        return Response(PayoutSerializer(services.settle_payout(payout)).data)


@extend_schema(tags=["platform"])
class PlatformPayoutMarkPaidView(APIView):
    permission_classes = [IsSuperAdmin]

    @extend_schema(request=None, responses=PayoutSerializer)
    def post(self, request, pk):
        payout = generics.get_object_or_404(Payout, pk=pk)
        return Response(PayoutSerializer(services.mark_payout_paid(payout)).data)
