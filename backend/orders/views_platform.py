"""Platform (super admin) order oversight: every store."""

from django.utils.dateparse import parse_date
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics

from core.pagination import HistoryCursorPagination
from core.permissions import IsSuperAdmin
from orders.models import Coupon, Order
from orders.serializers import CouponSerializer, OrderSummarySerializer


@extend_schema(tags=["platform"])
class PlatformOrderListView(generics.ListAPIView):
    permission_classes = [IsSuperAdmin]
    serializer_class = OrderSummarySerializer
    pagination_class = HistoryCursorPagination
    filter_backends = ()

    @extend_schema(
        parameters=[
            OpenApiParameter("store", str),
            OpenApiParameter("status", str),
            OpenApiParameter("from", str, description="ISO date"),
            OpenApiParameter("to", str, description="ISO date"),
        ]
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Order.objects.none()
        qs = Order.objects.select_related("store", "customer")
        params = self.request.query_params
        if store := params.get("store"):
            qs = qs.filter(store_id=store)
        if status_filter := params.get("status"):
            qs = qs.filter(status=status_filter)
        if from_date := parse_date(params.get("from", "")):
            qs = qs.filter(created_at__date__gte=from_date)
        if to_date := parse_date(params.get("to", "")):
            qs = qs.filter(created_at__date__lte=to_date)
        return qs


@extend_schema(tags=["platform"])
class PlatformCouponListCreateView(generics.ListCreateAPIView):
    """Platform-wide coupons: `store IS NULL`, usable at any store."""

    permission_classes = [IsSuperAdmin]
    serializer_class = CouponSerializer

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["store"] = None
        return ctx

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Coupon.objects.none()
        return Coupon.objects.filter(store__isnull=True)

    def perform_create(self, serializer):
        serializer.save(store=None)
