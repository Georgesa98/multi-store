"""Store dashboard order queue and the state-machine actions."""

from django.db.models import Q
from django.utils.dateparse import parse_date
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from core.enums import OrderStatus
from core.pagination import HistoryCursorPagination
from core.permissions import (
    IsDashboardUser,
    IsDashboardWriter,
    ReadWritePermissionsMixin,
)
from core.throttling import ScopedThrottleMixin
from core.views import PatchOnlyMixin
from delivery.serializers import TrackingTicketSerializer
from delivery.tickets import ticket_payload
from orders import services
from orders.models import Coupon, Order
from orders.serializers import (
    CancelOrderSerializer,
    CouponSerializer,
    OrderDetailSerializer,
    OrderSummarySerializer,
    OrderTransitionSerializer,
)


def _scoped(request):
    return (
        Order.objects.filter(store=request.store)
        .select_related("store", "customer", "delivery__company", "delivery__courier")
        .prefetch_related("items", "events__actor")
    )


@extend_schema(tags=["Dashboard orders"])
class DashboardOrderListView(ReadWritePermissionsMixin, generics.ListAPIView):
    serializer_class = OrderSummarySerializer
    pagination_class = HistoryCursorPagination
    filter_backends = ()

    @extend_schema(
        parameters=[
            OpenApiParameter("status", str),
            OpenApiParameter("from", str, description="ISO date"),
            OpenApiParameter("to", str, description="ISO date"),
            OpenApiParameter("q", str, description="Order number or customer"),
        ]
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Order.objects.none()
        qs = _scoped(self.request)
        params = self.request.query_params
        if status_filter := params.get("status"):
            qs = qs.filter(status=status_filter)
        if from_date := parse_date(params.get("from", "")):
            qs = qs.filter(created_at__date__gte=from_date)
        if to_date := parse_date(params.get("to", "")):
            qs = qs.filter(created_at__date__lte=to_date)
        if q := params.get("q"):
            qs = qs.filter(
                Q(number__icontains=q)
                | Q(customer__email__icontains=q)
                | Q(customer__full_name__icontains=q)
            )
        return qs


@extend_schema(tags=["Dashboard orders"])
class DashboardOrderDetailView(ReadWritePermissionsMixin, generics.RetrieveAPIView):
    serializer_class = OrderDetailSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Order.objects.none()
        return _scoped(self.request)


class _OrderTransitionView(APIView):
    permission_classes = [IsDashboardWriter]
    to_status: str = ""
    request_serializer = OrderTransitionSerializer

    @extend_schema(request=OrderTransitionSerializer, responses=OrderDetailSerializer)
    def post(self, request, pk):
        order = generics.get_object_or_404(_scoped(request), pk=pk)
        serializer = self.request_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        note = serializer.validated_data.get("reason", serializer.validated_data.get("note", ""))
        order = services.transition(
            order=order, to_status=self.to_status, actor=request.user, note=note
        )
        order = _scoped(request).get(pk=order.pk)
        return Response(OrderDetailSerializer(order).data, status=status.HTTP_200_OK)


@extend_schema(tags=["Dashboard orders"])
class DashboardOrderConfirmView(_OrderTransitionView):
    to_status = OrderStatus.CONFIRMED


@extend_schema(tags=["Dashboard orders"])
class DashboardOrderPreparingView(_OrderTransitionView):
    to_status = OrderStatus.PREPARING


@extend_schema(tags=["Dashboard orders"])
class DashboardOrderReadyView(_OrderTransitionView):
    to_status = OrderStatus.READY


@extend_schema(tags=["Dashboard orders"])
class DashboardOrderCancelView(_OrderTransitionView):
    to_status = OrderStatus.CANCELLED
    request_serializer = CancelOrderSerializer


@extend_schema(tags=["Dashboard orders"])
class DashboardOrderTicketView(ScopedThrottleMixin, APIView):
    """The store's ticket for watching its order's delivery."""

    permission_classes = [IsDashboardUser]
    throttle_scope = "ticket"

    @extend_schema(request=None, responses=TrackingTicketSerializer)
    def get(self, request, pk):
        order = generics.get_object_or_404(
            Order.objects.filter(store=request.store).select_related("delivery"), pk=pk
        )
        delivery = getattr(order, "delivery", None)
        if delivery is None:
            raise NotFound("This order has no delivery yet.")
        return Response(ticket_payload(user=request.user, delivery=delivery))


@extend_schema(tags=["Coupons"])
class DashboardCouponListCreateView(ReadWritePermissionsMixin, generics.ListCreateAPIView):
    serializer_class = CouponSerializer

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["store"] = self.request.store
        return ctx

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Coupon.objects.none()
        return Coupon.objects.filter(store=self.request.store)

    def perform_create(self, serializer):
        serializer.save(store=self.request.store)


@extend_schema(tags=["Coupons"])
class DashboardCouponDetailView(
    PatchOnlyMixin, ReadWritePermissionsMixin, generics.RetrieveUpdateDestroyAPIView
):
    serializer_class = CouponSerializer

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["store"] = self.request.store
        return ctx

    def get_queryset(self):
        return Coupon.objects.filter(store=self.request.store)

    def destroy(self, request, *args, **kwargs):
        coupon = self.get_object()
        coupon.is_active = False
        coupon.save(update_fields=["is_active", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)
