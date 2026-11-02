"""Platform (super admin) surface: store onboarding, approval, suspension, users."""

from django.contrib.auth import get_user_model
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.serializers import UserSerializer
from core.permissions import IsSuperAdmin
from stores import services
from stores.models import Store
from stores.serializers import (
    StoreOnboardSerializer,
    StorePlatformSerializer,
    SuspendStoreSerializer,
)

User = get_user_model()


@extend_schema(tags=["platform"])
class PlatformStoreListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsSuperAdmin]
    serializer_class = StorePlatformSerializer

    def get_queryset(self):
        qs = (
            Store.objects.select_related("owner")
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
        request=StoreOnboardSerializer,
        responses={201: StorePlatformSerializer},
        description="Create a store and invite its owner. The store starts as `pending`.",
    )
    def post(self, request, *args, **kwargs):
        serializer = StoreOnboardSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        store = services.create_store_with_owner(
            name=data.pop("name"),
            slug=data.pop("slug", ""),
            code=data.pop("code", ""),
            owner_email=data.pop("owner_email"),
            owner_full_name=data.pop("owner_full_name"),
            owner_phone=data.pop("owner_phone", ""),
            **data,
        )
        store = (
            Store.objects.select_related("owner")
            .prefetch_related("memberships__user")
            .get(pk=store.pk)
        )
        return Response(StorePlatformSerializer(store).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["platform"])
class PlatformStoreDetailView(generics.RetrieveAPIView):
    permission_classes = [IsSuperAdmin]
    serializer_class = StorePlatformSerializer
    queryset = Store.objects.select_related("owner").prefetch_related("memberships__user")


@extend_schema(tags=["platform"])
class PlatformStoreApproveView(APIView):
    permission_classes = [IsSuperAdmin]

    @extend_schema(request=None, responses=StorePlatformSerializer)
    def post(self, request, pk):
        store = generics.get_object_or_404(Store.objects.select_related("owner"), pk=pk)
        store = services.approve_store(store)
        return Response(StorePlatformSerializer(store).data)


@extend_schema(tags=["platform"])
class PlatformStoreSuspendView(APIView):
    permission_classes = [IsSuperAdmin]

    @extend_schema(request=SuspendStoreSerializer, responses=StorePlatformSerializer)
    def post(self, request, pk):
        serializer = SuspendStoreSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        store = generics.get_object_or_404(Store.objects.select_related("owner"), pk=pk)
        store = services.suspend_store(store, serializer.validated_data["reason"])
        return Response(StorePlatformSerializer(store).data)


@extend_schema(tags=["platform"])
class PlatformUserListView(generics.ListAPIView):
    permission_classes = [IsSuperAdmin]
    serializer_class = UserSerializer

    def get_queryset(self):
        qs = User.objects.all().order_by("-date_joined")
        role = self.request.query_params.get("role")
        if role:
            qs = qs.filter(role=role)
        q = self.request.query_params.get("q")
        if q:
            qs = qs.filter(email__icontains=q) | qs.filter(full_name__icontains=q)
        return qs


@extend_schema(tags=["platform"])
class PlatformUserDetailView(APIView):
    permission_classes = [IsSuperAdmin]

    @extend_schema(request=UserSerializer, responses=UserSerializer)
    def patch(self, request, pk):
        user = generics.get_object_or_404(User, pk=pk)
        if "is_active" in request.data:
            user.is_active = bool(request.data["is_active"])
            user.save(update_fields=["is_active"])
        if "full_name" in request.data:
            user.full_name = request.data["full_name"]
            user.save(update_fields=["full_name"])
        return Response(UserSerializer(user).data)
