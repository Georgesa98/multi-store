"""Courier surface: own profile, offered jobs, and the delivery flow."""

from django.utils.dateparse import parse_date
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from core.enums import DeliveryStatus
from core.permissions import IsCourier
from core.throttling import ScopedThrottleMixin
from delivery import services
from delivery.models import Delivery
from delivery.serializers import (
    CourierAvailabilitySerializer,
    CourierLocationSerializer,
    CourierSerializer,
    DeliveryDeliverSerializer,
    DeliveryFailSerializer,
    DeliveryJobDetailSerializer,
    DeliveryJobSerializer,
    DeliveryLocationSerializer,
    DeliveryReleaseSerializer,
    EarningsSerializer,
    TrackingTicketSerializer,
)
from delivery.tickets import ticket_payload


def _courier_scope(request):
    return (
        Delivery.objects.filter(courier=request.user)
        .select_related("order__store", "company", "courier__courier_profile", "zone")
        .prefetch_related("order__items", "events__actor")
    )


def _company_scope(request):
    return (
        Delivery.objects.filter(company_id=request.user.courier_profile.company_id)
        .select_related("order__store", "company", "courier__courier_profile", "zone")
        .prefetch_related("order__items", "events__actor")
    )


@extend_schema(tags=["courier"])
class CourierMeView(APIView):
    permission_classes = [IsCourier]

    @extend_schema(responses=dict)
    def get(self, request):
        profile = request.user.courier_profile
        return Response(
            {
                "profile": CourierSerializer(profile).data,
                "stats": services.courier_stats(request.user),
            }
        )


@extend_schema(tags=["courier"])
class CourierAvailabilityView(APIView):
    permission_classes = [IsCourier]

    @extend_schema(request=CourierAvailabilitySerializer, responses=CourierSerializer)
    def patch(self, request):
        serializer = CourierAvailabilitySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = request.user.courier_profile
        profile.is_available = serializer.validated_data["is_available"]
        profile.save(update_fields=["is_available", "updated_at"])
        return Response(CourierSerializer(profile).data)


@extend_schema(tags=["courier"])
class CourierOfferListView(generics.ListAPIView):
    permission_classes = [IsCourier]
    serializer_class = DeliveryJobSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Delivery.objects.none()
        return (
            _company_scope(self.request)
            .filter(status=DeliveryStatus.REQUESTED)
            .order_by("offered_at")
        )


@extend_schema(tags=["courier"])
class CourierDeliveryListView(generics.ListAPIView):
    permission_classes = [IsCourier]
    serializer_class = DeliveryJobSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter("status", str),
            OpenApiParameter("active", bool, description="Only in-flight deliveries"),
        ]
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Delivery.objects.none()
        qs = _courier_scope(self.request)
        params = self.request.query_params
        if status_filter := params.get("status"):
            qs = qs.filter(status=status_filter)
        if params.get("active") in ("true", "1", "True"):
            qs = qs.filter(status__in=services.ACTIVE_DELIVERY_STATUSES)
        return qs.order_by("-created_at")


@extend_schema(tags=["courier"])
class CourierDeliveryDetailView(generics.RetrieveAPIView):
    permission_classes = [IsCourier]
    serializer_class = DeliveryJobDetailSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Delivery.objects.none()
        return _courier_scope(self.request)


@extend_schema(tags=["courier"])
class CourierAcceptView(APIView):
    permission_classes = [IsCourier]

    @extend_schema(request=None, responses=DeliveryJobDetailSerializer)
    def post(self, request, pk):
        delivery = generics.get_object_or_404(_company_scope(request), pk=pk)
        delivery = services.accept_offer(delivery, courier=request.user)
        return Response(DeliveryJobDetailSerializer(_reload(request, delivery)).data)


@extend_schema(tags=["courier"])
class CourierDeclineView(APIView):
    permission_classes = [IsCourier]

    @extend_schema(request=DeliveryReleaseSerializer, responses=DeliveryJobDetailSerializer)
    def post(self, request, pk):
        delivery = generics.get_object_or_404(_company_scope(request), pk=pk)
        serializer = DeliveryReleaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        delivery = services.decline_offer(
            delivery, courier=request.user, note=serializer.validated_data.get("note", "")
        )
        return Response(DeliveryJobDetailSerializer(_reload(request, delivery)).data)


@extend_schema(tags=["courier"])
class CourierPickupView(APIView):
    permission_classes = [IsCourier]

    @extend_schema(request=None, responses=DeliveryJobDetailSerializer)
    def post(self, request, pk):
        delivery = generics.get_object_or_404(_courier_scope(request), pk=pk)
        delivery = services.pickup(delivery, courier=request.user)
        return Response(DeliveryJobDetailSerializer(_reload(request, delivery)).data)


@extend_schema(tags=["courier"])
class CourierLocationView(ScopedThrottleMixin, APIView):
    permission_classes = [IsCourier]
    throttle_scope = "location"

    @extend_schema(request=DeliveryLocationSerializer, responses=CourierLocationSerializer)
    def patch(self, request, pk):
        delivery = generics.get_object_or_404(_courier_scope(request), pk=pk)
        serializer = DeliveryLocationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        location = services.record_location(
            delivery=delivery, courier=request.user, **serializer.validated_data
        )
        return Response(CourierLocationSerializer(location).data)


@extend_schema(tags=["courier"])
class CourierDeliverView(APIView):
    permission_classes = [IsCourier]

    @extend_schema(request=DeliveryDeliverSerializer, responses=DeliveryJobDetailSerializer)
    def post(self, request, pk):
        delivery = generics.get_object_or_404(_courier_scope(request), pk=pk)
        serializer = DeliveryDeliverSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        delivery = services.deliver(
            delivery,
            courier=request.user,
            otp=data.get("otp", ""),
            proof_photo=data.get("proof_photo"),
            note=data.get("note", ""),
        )
        return Response(DeliveryJobDetailSerializer(_reload(request, delivery)).data)


@extend_schema(tags=["courier"])
class CourierFailView(APIView):
    permission_classes = [IsCourier]

    @extend_schema(request=DeliveryFailSerializer, responses=DeliveryJobDetailSerializer)
    def post(self, request, pk):
        delivery = generics.get_object_or_404(_courier_scope(request), pk=pk)
        serializer = DeliveryFailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        delivery = services.fail(
            delivery, actor=request.user, reason=serializer.validated_data["reason"]
        )
        # A failed job goes back to the company pool, so it is no longer
        # reachable through the courier's own deliveries: reload it by company.
        return Response(DeliveryJobDetailSerializer(_reload_company(request, delivery)).data)


def _reload(request, delivery) -> Delivery:
    return _courier_scope(request).get(pk=delivery.pk)


def _reload_company(request, delivery) -> Delivery:
    return _company_scope(request).get(pk=delivery.pk)


@extend_schema(tags=["courier"])
class CourierEarningsView(APIView):
    permission_classes = [IsCourier]

    @extend_schema(
        parameters=[
            OpenApiParameter("from", str, description="ISO date"),
            OpenApiParameter("to", str, description="ISO date"),
        ],
        responses=EarningsSerializer,
    )
    def get(self, request):
        data = services.courier_earnings(
            request.user,
            from_date=parse_date(request.query_params.get("from", "")),
            to_date=parse_date(request.query_params.get("to", "")),
        )
        return Response(EarningsSerializer(data).data)


@extend_schema(tags=["courier"])
class CourierTicketView(ScopedThrottleMixin, APIView):
    """A 60 s ticket for watching this delivery's socket."""

    permission_classes = [IsCourier]
    throttle_scope = "ticket"

    @extend_schema(request=None, responses=TrackingTicketSerializer)
    def post(self, request, pk):
        delivery = generics.get_object_or_404(_courier_scope(request), pk=pk)
        return Response(ticket_payload(user=request.user, delivery=delivery))
