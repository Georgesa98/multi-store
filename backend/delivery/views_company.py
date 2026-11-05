"""Delivery-company dashboard: own company, team, riders, zones and dispatch."""

from django.db.models import Q
from django.utils.dateparse import parse_date
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import CourierProfile
from core.enums import MemberRole
from core.exceptions import BusinessRuleViolation
from core.permissions import (
    CompanyReadWritePermissionsMixin,
    IsCompanyUser,
    IsCompanyWriter,
)
from core.throttling import ScopedThrottleMixin
from core.views import PatchOnlyMixin
from delivery import services
from delivery.models import CompanyMembership, Delivery, DeliveryZone
from delivery.serializers import (
    CompanyMemberInviteSerializer,
    CompanyMembershipSerializer,
    CourierCreateSerializer,
    CourierSerializer,
    CourierUpdateSerializer,
    DeliveryAssignSerializer,
    DeliveryCompanySerializer,
    DeliveryFailSerializer,
    DeliveryJobDetailSerializer,
    DeliveryJobSerializer,
    DeliveryReleaseSerializer,
    DeliveryZoneSerializer,
    EarningsSerializer,
    TrackingTicketSerializer,
)
from delivery.tickets import ticket_payload


@extend_schema(tags=["company"])
class CompanyDetailView(
    PatchOnlyMixin, CompanyReadWritePermissionsMixin, generics.RetrieveUpdateAPIView
):
    serializer_class = DeliveryCompanySerializer

    def get_object(self):
        return self.request.company


@extend_schema(tags=["company"])
class CompanyMemberListView(CompanyReadWritePermissionsMixin, generics.ListAPIView):
    serializer_class = CompanyMembershipSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return CompanyMembership.objects.none()
        return self.request.company.memberships.select_related("user").order_by("created_at")


@extend_schema(tags=["company"])
class CompanyMemberInviteView(ScopedThrottleMixin, APIView):
    permission_classes = [IsCompanyWriter]
    throttle_scope = "invite"

    @extend_schema(
        request=CompanyMemberInviteSerializer,
        responses={201: CompanyMembershipSerializer},
    )
    def post(self, request):
        serializer = CompanyMemberInviteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership = services.invite_company_member(
            company=request.company, **serializer.validated_data
        )
        membership = request.company.memberships.select_related("user").get(pk=membership.pk)
        return Response(
            CompanyMembershipSerializer(membership).data, status=status.HTTP_201_CREATED
        )


@extend_schema(tags=["company"])
class CompanyMemberDetailView(APIView):
    permission_classes = [IsCompanyWriter]

    @extend_schema(request=CompanyMembershipSerializer, responses=CompanyMembershipSerializer)
    def patch(self, request, pk):
        membership = generics.get_object_or_404(
            request.company.memberships.select_related("user"), pk=pk
        )
        if "is_active" in request.data:
            if membership.role == MemberRole.OWNER and not request.data["is_active"]:
                raise BusinessRuleViolation({"detail": "The company owner cannot be deactivated."})
            membership = services.set_company_member_active(
                membership, bool(request.data["is_active"])
            )
        if "role" in request.data:
            new_role = request.data["role"]
            if new_role not in (MemberRole.MANAGER, MemberRole.STAFF):
                raise BusinessRuleViolation(
                    {"role": ["Pick `manager` or `staff`; the owner role is fixed."]}
                )
            if membership.role == MemberRole.OWNER:
                raise BusinessRuleViolation({"role": ["The owner role is fixed."]})
            membership.role = new_role
            membership.save(update_fields=["role", "updated_at"])
        return Response(CompanyMembershipSerializer(membership).data)


@extend_schema(tags=["company"])
class CourierListView(CompanyReadWritePermissionsMixin, generics.ListCreateAPIView):
    serializer_class = CourierSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter("is_available", bool),
            OpenApiParameter("q", str, description="Name, email or phone"),
        ]
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(request=CourierCreateSerializer, responses={201: CourierSerializer})
    def post(self, request, *args, **kwargs):
        """The company hires its own riders; stores never create one."""
        serializer = CourierCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = services.create_courier(company=request.company, **serializer.validated_data)
        profile = CourierProfile.objects.select_related("user").get(pk=profile.pk)
        return Response(CourierSerializer(profile).data, status=status.HTTP_201_CREATED)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return CourierProfile.objects.none()
        qs = CourierProfile.objects.filter(company=self.request.company).select_related("user")
        params = self.request.query_params
        if params.get("is_available") in ("true", "1", "True"):
            qs = qs.filter(is_available=True)
        if q := params.get("q"):
            qs = qs.filter(
                Q(user__full_name__icontains=q)
                | Q(user__email__icontains=q)
                | Q(user__phone__icontains=q)
            )
        return qs.order_by("user__full_name")


@extend_schema(tags=["company"])
class CourierDetailView(APIView):
    permission_classes = [IsCompanyWriter]

    @extend_schema(request=CourierUpdateSerializer, responses=CourierSerializer)
    def patch(self, request, pk):
        profile = generics.get_object_or_404(
            CourierProfile.objects.select_related("user"), pk=pk, company=request.company
        )
        serializer = CourierUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if "is_active" in data and not data["is_active"]:
            services.deactivate_courier(profile)
        else:
            if "is_active" in data:
                profile.user.is_active = True
                profile.user.save(update_fields=["is_active"])
            for field in ("vehicle", "plate", "is_available"):
                if field in data:
                    setattr(profile, field, data[field])
            profile.save(update_fields=["vehicle", "plate", "is_available", "updated_at"])
        profile.refresh_from_db()
        return Response(CourierSerializer(profile).data)


@extend_schema(tags=["company"])
class ZoneListCreateView(CompanyReadWritePermissionsMixin, generics.ListCreateAPIView):
    serializer_class = DeliveryZoneSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return DeliveryZone.objects.none()
        return self.request.company.zones.all()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        membership = getattr(self.request, "company", None)
        context["company"] = membership
        return context

    def perform_create(self, serializer):
        serializer.save(company=self.request.company)


@extend_schema(tags=["company"])
class ZoneDetailView(
    PatchOnlyMixin, CompanyReadWritePermissionsMixin, generics.RetrieveUpdateDestroyAPIView
):
    serializer_class = DeliveryZoneSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return DeliveryZone.objects.none()
        return self.request.company.zones.all()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["company"] = getattr(self.request, "company", None)
        return context

    def perform_destroy(self, instance):
        # Zones may already be referenced by deliveries; retire, never delete.
        instance.is_active = False
        instance.save(update_fields=["is_active", "updated_at"])


def _delivery_scope(request):
    return (
        Delivery.objects.filter(company=request.company)
        .select_related("order__store", "company", "courier__courier_profile", "zone")
        .prefetch_related("order__items", "events__actor")
    )


@extend_schema(tags=["company"])
class DeliveryListView(CompanyReadWritePermissionsMixin, generics.ListAPIView):
    serializer_class = DeliveryJobSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter("status", str),
            OpenApiParameter("courier", str, description="Courier user UUID"),
            OpenApiParameter("active", bool, description="Only in-flight deliveries"),
        ]
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Delivery.objects.none()
        qs = _delivery_scope(self.request)
        params = self.request.query_params
        if status_filter := params.get("status"):
            qs = qs.filter(status=status_filter)
        if courier := params.get("courier"):
            qs = qs.filter(courier_id=courier)
        if params.get("active") in ("true", "1", "True"):
            qs = qs.filter(status__in=services.ACTIVE_DELIVERY_STATUSES)
        return qs.order_by("-created_at")


@extend_schema(tags=["company"])
class DeliveryDetailView(CompanyReadWritePermissionsMixin, generics.RetrieveAPIView):
    serializer_class = DeliveryJobDetailSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Delivery.objects.none()
        return _delivery_scope(self.request)


@extend_schema(tags=["company"])
class DeliveryAssignView(APIView):
    permission_classes = [IsCompanyWriter]

    @extend_schema(request=DeliveryAssignSerializer, responses=DeliveryJobDetailSerializer)
    def post(self, request, pk):
        delivery = generics.get_object_or_404(_delivery_scope(request), pk=pk)
        serializer = DeliveryAssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        courier = generics.get_object_or_404(
            CourierProfile.objects.select_related("user"),
            pk=serializer.validated_data["courier_id"],
            company=request.company,
        )
        delivery = services.assign_courier(delivery, courier=courier.user, actor=request.user)
        return Response(DeliveryJobDetailSerializer(_reload(request, delivery)).data)


@extend_schema(tags=["company"])
class DeliveryReleaseView(APIView):
    permission_classes = [IsCompanyWriter]

    @extend_schema(request=DeliveryReleaseSerializer, responses=DeliveryJobDetailSerializer)
    def post(self, request, pk):
        delivery = generics.get_object_or_404(_delivery_scope(request), pk=pk)
        serializer = DeliveryReleaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        delivery = services.release_delivery(
            delivery, actor=request.user, note=serializer.validated_data.get("note", "")
        )
        return Response(DeliveryJobDetailSerializer(_reload(request, delivery)).data)


@extend_schema(tags=["company"])
class DeliveryFailView(APIView):
    permission_classes = [IsCompanyWriter]

    @extend_schema(request=DeliveryFailSerializer, responses=DeliveryJobDetailSerializer)
    def post(self, request, pk):
        delivery = generics.get_object_or_404(_delivery_scope(request), pk=pk)
        serializer = DeliveryFailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        delivery = services.fail(
            delivery, actor=request.user, reason=serializer.validated_data["reason"]
        )
        return Response(DeliveryJobDetailSerializer(_reload(request, delivery)).data)


def _reload(request, delivery) -> Delivery:
    return _delivery_scope(request).get(pk=delivery.pk)


@extend_schema(tags=["company"])
class CompanyEarningsView(APIView):
    permission_classes = [IsCompanyUser]

    @extend_schema(
        parameters=[
            OpenApiParameter("from", str, description="ISO date"),
            OpenApiParameter("to", str, description="ISO date"),
        ],
        responses=EarningsSerializer,
    )
    def get(self, request):
        data = services.company_earnings(
            request.company,
            from_date=parse_date(request.query_params.get("from", "")),
            to_date=parse_date(request.query_params.get("to", "")),
        )
        return Response(EarningsSerializer(data).data)


@extend_schema(tags=["company"])
class CompanyDeliveryTicketView(ScopedThrottleMixin, APIView):
    """Dispatchers watch the same socket the customer and courier do."""

    permission_classes = [IsCompanyUser]
    throttle_scope = "ticket"

    @extend_schema(request=None, responses=TrackingTicketSerializer)
    def get(self, request, pk):
        delivery = generics.get_object_or_404(
            Delivery.objects.filter(company=request.company), pk=pk
        )
        return Response(ticket_payload(user=request.user, delivery=delivery))
