"""Store dashboard surface: own store only, staff read-only."""

from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import ReadWritePermissionsMixin
from core.views import PatchOnlyMixin
from stores import services
from stores.serializers import (
    OpeningHoursBulkSerializer,
    OpeningHoursSerializer,
    StoreDashboardSerializer,
)


@extend_schema(tags=["Store profile"])
class StoreDetailView(PatchOnlyMixin, ReadWritePermissionsMixin, generics.RetrieveUpdateAPIView):
    serializer_class = StoreDashboardSerializer

    def get_object(self):
        return self.request.store


@extend_schema(tags=["Store profile"])
class OpeningHoursView(ReadWritePermissionsMixin, APIView):
    @extend_schema(responses=OpeningHoursSerializer(many=True))
    def get(self, request):
        rows = request.store.opening_hours.all()
        return Response(OpeningHoursSerializer(rows, many=True).data)

    @extend_schema(request=OpeningHoursBulkSerializer, responses=OpeningHoursSerializer(many=True))
    def patch(self, request):
        serializer = OpeningHoursBulkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        rows = services.replace_opening_hours(request.store, serializer.validated_data["hours"])
        return Response(OpeningHoursSerializer(rows, many=True).data)
