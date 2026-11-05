"""Customer address book. Every row is scoped to the caller."""

from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts import services
from accounts.models import Address
from accounts.serializers import AddressSerializer
from core.permissions import IsCustomer
from core.views import PatchOnlyMixin


@extend_schema(tags=["Addresses"])
class AddressListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsCustomer]
    serializer_class = AddressSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Address.objects.none()
        return Address.objects.filter(customer=self.request.user)

    def perform_create(self, serializer):
        address = services.create_address(customer=self.request.user, **serializer.validated_data)
        serializer.instance = address


@extend_schema(tags=["Addresses"])
class AddressDetailView(PatchOnlyMixin, generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsCustomer]
    serializer_class = AddressSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Address.objects.none()
        return Address.objects.filter(customer=self.request.user)

    def update(self, request, *args, **kwargs):
        address = self.get_object()
        serializer = AddressSerializer(address, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        address = services.update_address(address, **serializer.validated_data)
        return Response(AddressSerializer(address).data)


@extend_schema(tags=["Addresses"])
class AddressSetDefaultView(APIView):
    permission_classes = [IsCustomer]

    @extend_schema(request=None, responses=AddressSerializer)
    def post(self, request, pk):
        address = generics.get_object_or_404(Address, pk=pk, customer=request.user)
        address = services.set_default_address(address)
        return Response(AddressSerializer(address).data)
