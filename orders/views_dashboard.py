"""Store dashboard order queue and the state-machine actions."""

from django.db.models import Q
from django.utils.dateparse import parse_date
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.enums import OrderStatus
from core.permissions import (
    IsDashboardWriter,
    ReadWritePermissionsMixin,
)
from orders import services
from orders.models import Order
from orders.serializers import (
    CancelOrderSerializer,
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


@extend_schema(tags=["dashboard"])
class DashboardOrderListView(ReadWritePermissionsMixin, generics.ListAPIView):
    serializer_class = OrderSummarySerializer

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
        return qs.order_by("-created_at")


@extend_schema(tags=["dashboard"])
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


@extend_schema(tags=["dashboard"])
class DashboardOrderConfirmView(_OrderTransitionView):
    to_status = OrderStatus.CONFIRMED


@extend_schema(tags=["dashboard"])
class DashboardOrderPreparingView(_OrderTransitionView):
    to_status = OrderStatus.PREPARING


@extend_schema(tags=["dashboard"])
class DashboardOrderReadyView(_OrderTransitionView):
    to_status = OrderStatus.READY


@extend_schema(tags=["dashboard"])
class DashboardOrderCancelView(_OrderTransitionView):
    to_status = OrderStatus.CANCELLED
    request_serializer = CancelOrderSerializer
