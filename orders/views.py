"""Customer checkout and order history. Every query is scoped to the caller."""

from django.utils.dateparse import parse_date
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Address
from core.exceptions import BusinessRuleViolation
from core.permissions import IsCustomer
from delivery.serializers import TrackingTicketSerializer
from delivery.tickets import ticket_payload
from orders import services
from orders.models import CheckoutGroup, Order
from orders.serializers import (
    CancelOrderSerializer,
    CheckoutGroupSerializer,
    CheckoutPreviewSerializer,
    CheckoutRequestSerializer,
    OrderDetailSerializer,
    OrderStatusEventSerializer,
    OrderSummarySerializer,
)


def _address_for(request, address_id):
    if not address_id:
        return None
    return generics.get_object_or_404(Address, pk=address_id, customer=request.user)


def _apply_order_filters(qs, params):
    if status_filter := params.get("status"):
        qs = qs.filter(status=status_filter)
    if store := params.get("store"):
        qs = qs.filter(store_id=store)
    if from_date := parse_date(params.get("from", "")):
        qs = qs.filter(created_at__date__gte=from_date)
    if to_date := parse_date(params.get("to", "")):
        qs = qs.filter(created_at__date__lte=to_date)
    return qs


@extend_schema(tags=["orders"])
class CheckoutPreviewView(APIView):
    permission_classes = [IsCustomer]

    @extend_schema(
        parameters=[
            OpenApiParameter("address_id", str, description="Saved address UUID"),
            OpenApiParameter("store_ids", str, description="Comma-separated store UUIDs"),
        ],
        responses=CheckoutPreviewSerializer,
    )
    def get(self, request):
        address = _address_for(request, request.query_params.get("address_id"))
        raw_stores = request.query_params.get("store_ids", "")
        store_ids = [part for part in raw_stores.split(",") if part]
        data = services.preview(customer=request.user, address=address, store_ids=store_ids or None)
        return Response(CheckoutPreviewSerializer(data, context={"request": request}).data)


@extend_schema(tags=["orders"])
class CheckoutView(APIView):
    permission_classes = [IsCustomer]

    @extend_schema(
        request=CheckoutRequestSerializer,
        responses={201: CheckoutGroupSerializer, 200: CheckoutGroupSerializer},
        description=(
            "Checkout every store's cart at once. Requires an `Idempotency-Key` "
            "header; replaying the same key returns the original group."
        ),
    )
    def post(self, request):
        idempotency_key = request.headers.get("Idempotency-Key", "").strip()
        if not idempotency_key:
            raise BusinessRuleViolation({"detail": "An Idempotency-Key header is required."})
        if len(idempotency_key) > 128:
            raise BusinessRuleViolation(
                {"detail": "Idempotency-Key must be 128 characters or fewer."}
            )

        serializer = CheckoutRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        address = _address_for(request, data["address_id"])

        replay = CheckoutGroup.objects.filter(
            idempotency_key=idempotency_key, customer=request.user
        ).exists()
        group = services.checkout(
            customer=request.user,
            address=address,
            store_ids=data.get("store_ids") or None,
            notes=data.get("notes", ""),
            idempotency_key=idempotency_key,
        )
        group = (
            CheckoutGroup.objects.prefetch_related("orders__store", "orders__customer")
            .select_related("customer")
            .get(pk=group.pk)
        )
        return Response(
            CheckoutGroupSerializer(group).data,
            status=status.HTTP_200_OK if replay else status.HTTP_201_CREATED,
        )


@extend_schema(tags=["orders"])
class CheckoutGroupListView(generics.ListAPIView):
    permission_classes = [IsCustomer]
    serializer_class = CheckoutGroupSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return CheckoutGroup.objects.none()
        return CheckoutGroup.objects.filter(customer=self.request.user).prefetch_related(
            "orders__store", "orders__customer"
        )


@extend_schema(tags=["orders"])
class CheckoutGroupDetailView(generics.RetrieveAPIView):
    permission_classes = [IsCustomer]
    serializer_class = CheckoutGroupSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return CheckoutGroup.objects.none()
        return CheckoutGroup.objects.filter(customer=self.request.user).prefetch_related(
            "orders__store", "orders__customer"
        )


@extend_schema(tags=["orders"])
class OrderListView(generics.ListAPIView):
    permission_classes = [IsCustomer]
    serializer_class = OrderSummarySerializer

    @extend_schema(
        parameters=[
            OpenApiParameter("status", str),
            OpenApiParameter("store", str),
            OpenApiParameter("from", str, description="ISO date"),
            OpenApiParameter("to", str, description="ISO date"),
        ]
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Order.objects.none()
        qs = Order.objects.filter(customer=self.request.user).select_related("store", "customer")
        return _apply_order_filters(qs, self.request.query_params)


@extend_schema(tags=["orders"])
class OrderDetailView(generics.RetrieveAPIView):
    permission_classes = [IsCustomer]
    serializer_class = OrderDetailSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Order.objects.none()
        return (
            Order.objects.filter(customer=self.request.user)
            .select_related("store", "customer", "delivery__company", "delivery__courier")
            .prefetch_related("items", "events__actor")
        )


@extend_schema(tags=["orders"])
class OrderTimelineView(APIView):
    permission_classes = [IsCustomer]

    @extend_schema(responses=OrderStatusEventSerializer(many=True))
    def get(self, request, pk):
        order = generics.get_object_or_404(Order, pk=pk, customer=request.user)
        events = order.events.select_related("actor").all()
        return Response(OrderStatusEventSerializer(events, many=True).data)


@extend_schema(tags=["orders"])
class OrderCancelView(APIView):
    permission_classes = [IsCustomer]

    @extend_schema(request=CancelOrderSerializer, responses=OrderDetailSerializer)
    def post(self, request, pk):
        order = generics.get_object_or_404(Order, pk=pk, customer=request.user)
        serializer = CancelOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = services.cancel(
            order=order,
            actor=request.user,
            reason=serializer.validated_data.get("reason", ""),
        )
        order = (
            Order.objects.select_related(
                "store", "customer", "delivery__company", "delivery__courier"
            )
            .prefetch_related("items", "events__actor")
            .get(pk=order.pk)
        )
        return Response(OrderDetailSerializer(order).data)


@extend_schema(tags=["orders"])
class OrderTicketView(APIView):
    """The customer's short-lived ticket for the delivery socket."""

    permission_classes = [IsCustomer]

    @extend_schema(request=None, responses=TrackingTicketSerializer)
    def get(self, request, pk):
        order = generics.get_object_or_404(
            Order.objects.filter(customer=request.user).select_related("delivery"), pk=pk
        )
        delivery = getattr(order, "delivery", None)
        if delivery is None:
            raise NotFound("This order has no delivery yet.")
        return Response(ticket_payload(user=request.user, delivery=delivery))
