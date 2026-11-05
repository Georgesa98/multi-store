"""Platform surface for delivery companies: onboarding, approval, suspension."""

from django.utils.dateparse import parse_date
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import IsSuperAdmin
from delivery import services
from delivery.models import Delivery, DeliveryCompany
from delivery.serializers import (
    DeliveryCompanyOnboardSerializer,
    DeliveryCompanySerializer,
    DeliveryJobSerializer,
    SuspendCompanySerializer,
)


@extend_schema(tags=["Platform companies"])
class PlatformCompanyListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsSuperAdmin]
    serializer_class = DeliveryCompanySerializer

    def get_queryset(self):
        qs = (
            DeliveryCompany.objects.select_related("owner")
            .prefetch_related("memberships__user")
            .order_by("-created_at")
        )
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        q = self.request.query_params.get("q")
        if q:
            qs = qs.filter(name__icontains=q)
        return qs

    @extend_schema(
        request=DeliveryCompanyOnboardSerializer,
        responses={201: DeliveryCompanySerializer},
        description="Create a delivery company and invite its owner; it starts as `pending`.",
    )
    def post(self, request, *args, **kwargs):
        serializer = DeliveryCompanyOnboardSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        company = services.create_company_with_owner(
            name=data.pop("name"),
            slug=data.pop("slug", ""),
            owner_email=data.pop("owner_email"),
            owner_full_name=data.pop("owner_full_name"),
            owner_phone=data.pop("owner_phone", ""),
            **data,
        )
        company = (
            DeliveryCompany.objects.select_related("owner")
            .prefetch_related("memberships__user")
            .get(pk=company.pk)
        )
        return Response(DeliveryCompanySerializer(company).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["Platform companies"])
class PlatformCompanyDetailView(generics.RetrieveAPIView):
    permission_classes = [IsSuperAdmin]
    serializer_class = DeliveryCompanySerializer
    queryset = DeliveryCompany.objects.select_related("owner").prefetch_related("memberships__user")


@extend_schema(tags=["Platform companies"])
class PlatformCompanyApproveView(APIView):
    permission_classes = [IsSuperAdmin]

    @extend_schema(request=None, responses=DeliveryCompanySerializer)
    def post(self, request, pk):
        company = generics.get_object_or_404(DeliveryCompany.objects.select_related("owner"), pk=pk)
        company = services.approve_company(company)
        return Response(DeliveryCompanySerializer(company).data)


@extend_schema(tags=["Platform companies"])
class PlatformCompanySuspendView(APIView):
    permission_classes = [IsSuperAdmin]

    @extend_schema(request=SuspendCompanySerializer, responses=DeliveryCompanySerializer)
    def post(self, request, pk):
        serializer = SuspendCompanySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        company = generics.get_object_or_404(DeliveryCompany.objects.select_related("owner"), pk=pk)
        company = services.suspend_company(company, serializer.validated_data["reason"])
        return Response(DeliveryCompanySerializer(company).data)


@extend_schema(tags=["Orders and deliveries"])
class PlatformDeliveryListView(generics.ListAPIView):
    permission_classes = [IsSuperAdmin]
    serializer_class = DeliveryJobSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter("status", str),
            OpenApiParameter("company", str),
            OpenApiParameter("store", str),
            OpenApiParameter("from", str, description="ISO date"),
            OpenApiParameter("to", str, description="ISO date"),
        ]
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Delivery.objects.none()
        qs = (
            Delivery.objects.select_related(
                "order__store", "company", "courier__courier_profile", "zone"
            )
            .prefetch_related("order__items")
            .order_by("-created_at")
        )
        params = self.request.query_params
        if status_filter := params.get("status"):
            qs = qs.filter(status=status_filter)
        if company := params.get("company"):
            qs = qs.filter(company_id=company)
        if store := params.get("store"):
            qs = qs.filter(store_id=store)
        if from_date := parse_date(params.get("from", "")):
            qs = qs.filter(created_at__date__gte=from_date)
        if to_date := parse_date(params.get("to", "")):
            qs = qs.filter(created_at__date__lte=to_date)
        return qs
