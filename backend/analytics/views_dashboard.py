"""Store insights: rollups for past days, live figures for today."""

from datetime import timedelta

from django.utils.dateparse import parse_date
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from analytics import services
from analytics.models import LedgerEntry
from analytics.serializers import (
    DailyStoreStatSerializer,
    DeliveryPerformanceSerializer,
    InsightSummarySerializer,
    LedgerEntrySerializer,
    OrdersByStatusSerializer,
    TopProductSerializer,
)
from core.exceptions import BusinessRuleViolation
from core.permissions import IsDashboardUser

DEFAULT_WINDOW_DAYS = 29


def day_range(request) -> tuple:
    """`?from&to` as report-zone dates; defaults to the last 30 days."""
    today = services.report_date()
    from_day = parse_date(request.query_params.get("from", "")) or today - timedelta(
        days=DEFAULT_WINDOW_DAYS
    )
    to_day = parse_date(request.query_params.get("to", "")) or today
    if to_day < from_day:
        raise BusinessRuleViolation({"detail": "`to` must not be before `from`."})
    return from_day, to_day


def range_parameters() -> list:
    return [
        OpenApiParameter("from", str, description="ISO date (default: 30 days ago)"),
        OpenApiParameter("to", str, description="ISO date (default: today)"),
    ]


@extend_schema(tags=["Insights"])
class DashboardInsightSummaryView(APIView):
    permission_classes = [IsDashboardUser]

    @extend_schema(parameters=range_parameters(), responses=InsightSummarySerializer)
    def get(self, request):
        data = services.store_summary(request.store, *day_range(request))
        return Response(InsightSummarySerializer(data).data)


@extend_schema(tags=["Insights"])
class DashboardRevenueView(APIView):
    permission_classes = [IsDashboardUser]

    @extend_schema(parameters=range_parameters(), responses=DailyStoreStatSerializer(many=True))
    def get(self, request):
        data = services.store_series(request.store, *day_range(request))
        return Response(DailyStoreStatSerializer(data, many=True).data)


@extend_schema(tags=["Insights"])
class DashboardTopProductsView(APIView):
    permission_classes = [IsDashboardUser]

    @extend_schema(parameters=range_parameters(), responses=TopProductSerializer(many=True))
    def get(self, request):
        data = services.product_totals(request.store, *day_range(request))
        return Response(TopProductSerializer(data, many=True).data)


@extend_schema(tags=["Insights"])
class DashboardOrdersByStatusView(APIView):
    permission_classes = [IsDashboardUser]

    @extend_schema(parameters=range_parameters(), responses=OrdersByStatusSerializer(many=True))
    def get(self, request):
        data = services.orders_by_status(request.store, *day_range(request))
        return Response(OrdersByStatusSerializer(data, many=True).data)


@extend_schema(tags=["Insights"])
class DashboardDeliveryPerformanceView(APIView):
    permission_classes = [IsDashboardUser]

    @extend_schema(parameters=range_parameters(), responses=DeliveryPerformanceSerializer)
    def get(self, request):
        data = services.delivery_performance(request.store, *day_range(request))
        return Response(DeliveryPerformanceSerializer(data).data)


@extend_schema(tags=["Insights"])
class DashboardLedgerView(generics.ListAPIView):
    """The store's own append-only ledger."""

    permission_classes = [IsDashboardUser]
    serializer_class = LedgerEntrySerializer

    @extend_schema(
        parameters=range_parameters()
        + [OpenApiParameter("kind", str, description="sale, refund, commission, payout")]
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return LedgerEntry.objects.none()
        queryset = services.ledger_for_store(self.request.store)
        params = self.request.query_params
        if kind := params.get("kind"):
            queryset = queryset.filter(kind=kind)
        from_day, to_day = day_range(self.request)
        start, end = services.range_bounds(from_day, to_day)
        return queryset.filter(created_at__gte=start, created_at__lt=end)
