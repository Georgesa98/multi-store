"""Store side of delivery: contracts with companies and requesting a courier."""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.enums import CompanyStatus
from core.permissions import IsDashboardUser, IsDashboardWriter, ReadWritePermissionsMixin
from delivery import services
from delivery.models import Delivery, DeliveryCompany, StoreDeliveryPartner
from delivery.serializers import (
    DeliveryCompanyBriefSerializer,
    DeliveryJobDetailSerializer,
    DeliveryJobSerializer,
    DeliveryRequestSerializer,
    PartnerCreateSerializer,
    PartnerSerializer,
    PartnerUpdateSerializer,
)


@extend_schema(tags=["Delivery partners"])
class AvailableCompanyListView(generics.ListAPIView):
    """Approved companies a store may contract."""

    serializer_class = DeliveryCompanyBriefSerializer
    permission_classes = [IsDashboardUser]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return DeliveryCompany.objects.none()
        return DeliveryCompany.objects.filter(status=CompanyStatus.ACTIVE).order_by("name")


@extend_schema(tags=["Delivery partners"])
class PartnerListView(ReadWritePermissionsMixin, generics.ListCreateAPIView):
    serializer_class = PartnerSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return StoreDeliveryPartner.objects.none()
        return (
            StoreDeliveryPartner.objects.filter(store=self.request.store)
            .select_related("company")
            .order_by("priority", "created_at")
        )

    @extend_schema(request=PartnerCreateSerializer, responses={201: PartnerSerializer})
    def post(self, request, *args, **kwargs):
        """Contract a company; re-contracting an old partner reactivates it."""
        serializer = PartnerCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        company = generics.get_object_or_404(
            DeliveryCompany, pk=serializer.validated_data["company_id"]
        )
        partner = services.activate_partner(
            store=request.store,
            company=company,
            priority=serializer.validated_data.get("priority", 0),
        )
        partner = StoreDeliveryPartner.objects.select_related("company").get(pk=partner.pk)
        return Response(PartnerSerializer(partner).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["Delivery partners"])
class PartnerCreateView(APIView):
    permission_classes = [IsDashboardWriter]

    @extend_schema(request=PartnerCreateSerializer, responses={201: PartnerSerializer})
    def post(self, request):
        serializer = PartnerCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        company = generics.get_object_or_404(
            DeliveryCompany, pk=serializer.validated_data["company_id"]
        )
        partner = services.activate_partner(
            store=request.store,
            company=company,
            priority=serializer.validated_data.get("priority", 0),
        )
        partner = StoreDeliveryPartner.objects.select_related("company").get(pk=partner.pk)
        return Response(PartnerSerializer(partner).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["Delivery partners"])
class PartnerDetailView(APIView):
    permission_classes = [IsDashboardWriter]

    @extend_schema(request=PartnerUpdateSerializer, responses=PartnerSerializer)
    def patch(self, request, pk):
        partner = generics.get_object_or_404(
            StoreDeliveryPartner.objects.select_related("company"),
            pk=pk,
            store=request.store,
        )
        serializer = PartnerUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        partner = services.set_partner(partner, **serializer.validated_data)
        return Response(PartnerSerializer(partner).data)

    @extend_schema(request=None, responses={204: None})
    def delete(self, request, pk):
        partner = generics.get_object_or_404(StoreDeliveryPartner, pk=pk, store=request.store)
        services.set_partner(partner, is_active=False)
        return Response(status=status.HTTP_204_NO_CONTENT)


def _delivery_scope(request):
    return (
        Delivery.objects.filter(store=request.store)
        .select_related("order__store", "company", "courier__courier_profile", "zone")
        .prefetch_related("order__items", "events__actor")
    )


@extend_schema(tags=["Delivery partners"])
class StoreDeliveryListView(generics.ListAPIView):
    serializer_class = DeliveryJobSerializer
    permission_classes = [IsDashboardUser]

    @extend_schema(
        parameters=[
            OpenApiParameter("status", str),
            OpenApiParameter("company", str, description="Delivery company UUID"),
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
        if company := params.get("company"):
            qs = qs.filter(company_id=company)
        return qs.order_by("-created_at")


@extend_schema(tags=["Delivery partners"])
class StoreDeliveryDetailView(generics.RetrieveAPIView):
    serializer_class = DeliveryJobDetailSerializer
    permission_classes = [IsDashboardUser]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Delivery.objects.none()
        return _delivery_scope(self.request)


@extend_schema(tags=["Delivery partners"])
class StoreDeliveryRequestView(APIView):
    """Ask the contracted company (optionally another partner) to take the job."""

    permission_classes = [IsDashboardWriter]

    @extend_schema(request=DeliveryRequestSerializer, responses=DeliveryJobDetailSerializer)
    def post(self, request, pk):
        delivery = generics.get_object_or_404(_delivery_scope(request), pk=pk)
        serializer = DeliveryRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        company = None
        company_id = serializer.validated_data.get("company_id")
        if company_id:
            company = generics.get_object_or_404(DeliveryCompany, pk=company_id)
        delivery = services.request_delivery(delivery, actor=request.user, company=company)
        delivery = _delivery_scope(request).get(pk=delivery.pk)
        return Response(DeliveryJobDetailSerializer(delivery).data)
