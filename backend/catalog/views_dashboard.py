"""Catalogue management on the store dashboard surface."""

from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from catalog import services
from catalog.models import Category, InventoryMovement, Product, ProductVariant
from catalog.serializers import (
    CategorySerializer,
    InventoryMovementSerializer,
    ProductCreateSerializer,
    ProductDashboardSerializer,
    ProductImageSerializer,
    ProductUpdateSerializer,
    ProductVariantWriteSerializer,
    StockAdjustSerializer,
    VariantCreateSerializer,
)
from core.permissions import (
    IsDashboardUser,
    IsDashboardWriter,
    ReadWritePermissionsMixin,
)
from core.views import PatchOnlyMixin


@extend_schema(tags=["dashboard"])
class CategoryListCreateView(ReadWritePermissionsMixin, generics.ListCreateAPIView):
    serializer_class = CategorySerializer

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["store"] = self.request.store
        return ctx

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Category.objects.none()
        return Category.objects.filter(store=self.request.store).select_related("parent")

    def perform_create(self, serializer):
        serializer.save(store=self.request.store)


@extend_schema(tags=["dashboard"])
class CategoryDetailView(
    PatchOnlyMixin, ReadWritePermissionsMixin, generics.RetrieveUpdateDestroyAPIView
):
    serializer_class = CategorySerializer

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["store"] = self.request.store
        return ctx

    def get_queryset(self):
        return Category.objects.filter(store=self.request.store)

    def destroy(self, request, *args, **kwargs):
        category = self.get_object()
        category.is_active = False
        category.save(update_fields=["is_active", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["dashboard"])
class ProductListCreateView(ReadWritePermissionsMixin, generics.ListCreateAPIView):
    @extend_schema(
        parameters=[
            OpenApiParameter("q", str),
            OpenApiParameter("status", str),
            OpenApiParameter("category", str, description="Category UUID or slug"),
        ]
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_serializer_class(self):
        return (
            ProductCreateSerializer if self.request.method == "POST" else ProductDashboardSerializer
        )

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Product.objects.none()
        qs = (
            Product.objects.filter(store=self.request.store)
            .select_related("category")
            .prefetch_related("images", "variants")
        )
        params = self.request.query_params
        if q := params.get("q"):
            qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q))
        if status_filter := params.get("status"):
            qs = qs.filter(status=status_filter)
        if category := params.get("category"):
            try:
                qs = qs.filter(category_id=category)
            except (ValueError, TypeError):
                qs = qs.filter(category__slug=category)
        return qs.order_by("name")

    @extend_schema(request=ProductCreateSerializer, responses={201: ProductDashboardSerializer})
    def post(self, request, *args, **kwargs):
        serializer = ProductCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)

        category = None
        if data.get("category"):
            category = Category.objects.filter(
                Q(store=request.store) | Q(store__isnull=True), pk=data["category"]
            ).first()
            if category is None:
                return Response(
                    {"category": ["Category not found."]},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        product, _variant = services.create_product(
            store=request.store,
            category=category,
            actor=request.user,
            **{k: v for k, v in data.items() if k != "category"},
        )
        product = (
            Product.objects.select_related("category")
            .prefetch_related("images", "variants")
            .get(pk=product.pk)
        )
        return Response(ProductDashboardSerializer(product).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["dashboard"])
class ProductDetailView(
    PatchOnlyMixin, ReadWritePermissionsMixin, generics.RetrieveUpdateDestroyAPIView
):
    def get_serializer_class(self):
        return (
            ProductUpdateSerializer
            if self.request.method in ("PATCH", "PUT")
            else ProductDashboardSerializer
        )

    def get_queryset(self):
        return (
            Product.objects.filter(store=self.request.store)
            .select_related("category")
            .prefetch_related("images", "variants")
        )

    def update(self, request, *args, **kwargs):
        product = self.get_object()
        serializer = ProductUpdateSerializer(product, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        product = services.update_product(product, **serializer.validated_data)
        product = self.get_queryset().get(pk=product.pk)
        return Response(ProductDashboardSerializer(product).data)

    def destroy(self, request, *args, **kwargs):
        product = services.archive_product(self.get_object())
        return Response(ProductDashboardSerializer(product).data, status=status.HTTP_200_OK)

    @extend_schema(responses={200: ProductDashboardSerializer})
    def delete(self, request, *args, **kwargs):
        """Archive, not remove: the product may appear on historical orders."""
        return self.destroy(request, *args, **kwargs)


@extend_schema(tags=["dashboard"])
class ProductImageUploadView(APIView):
    permission_classes = [IsDashboardWriter]

    @extend_schema(request=ProductImageSerializer, responses={201: ProductImageSerializer})
    def post(self, request, pk):
        product = generics.get_object_or_404(Product, pk=pk, store=request.store)
        serializer = ProductImageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        image = services.add_image(
            product=product,
            image=serializer.validated_data["image"],
            alt=serializer.validated_data.get("alt", ""),
            sort_order=serializer.validated_data.get("sort_order", 0),
        )
        return Response(
            ProductImageSerializer(image, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema(tags=["dashboard"])
class ProductVariantCreateView(APIView):
    permission_classes = [IsDashboardWriter]

    @extend_schema(request=VariantCreateSerializer, responses={201: dict})
    def post(self, request, pk):
        product = generics.get_object_or_404(Product, pk=pk, store=request.store)
        serializer = VariantCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        variant = services.add_variant(
            product=product, actor=request.user, **serializer.validated_data
        )
        from catalog.serializers import ProductVariantSerializer

        return Response(ProductVariantSerializer(variant).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["dashboard"])
class VariantDetailView(PatchOnlyMixin, generics.UpdateAPIView):
    permission_classes = [IsDashboardWriter]
    serializer_class = ProductVariantWriteSerializer

    def get_queryset(self):
        return ProductVariant.objects.filter(product__store=self.request.store)

    def update(self, request, *args, **kwargs):
        variant = self.get_object()
        serializer = ProductVariantWriteSerializer(variant, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        variant = services.update_variant(variant, **serializer.validated_data)
        from catalog.serializers import ProductVariantSerializer

        return Response(ProductVariantSerializer(variant).data)


@extend_schema(tags=["dashboard"])
class VariantStockView(APIView):
    permission_classes = [IsDashboardWriter]

    @extend_schema(request=StockAdjustSerializer, responses={201: dict})
    def post(self, request, pk):
        variant = generics.get_object_or_404(
            ProductVariant.objects.select_related("product"),
            pk=pk,
            product__store=request.store,
        )
        serializer = StockAdjustSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        movement = services.adjust_stock(
            variant=variant,
            delta=data["delta"],
            reason=data["reason"],
            note=data.get("note", ""),
            actor=request.user,
        )
        variant.refresh_from_db()
        from catalog.serializers import ProductVariantSerializer

        return Response(
            {
                "variant": ProductVariantSerializer(variant).data,
                "movement": InventoryMovementSerializer(movement).data,
            },
            status=status.HTTP_201_CREATED,
        )


@extend_schema(tags=["dashboard"])
class InventoryMovementListView(generics.ListAPIView):
    permission_classes = [IsDashboardUser]
    serializer_class = InventoryMovementSerializer

    @extend_schema(parameters=[OpenApiParameter("variant", str)])
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return InventoryMovement.objects.none()
        qs = InventoryMovement.objects.filter(
            variant__product__store=self.request.store
        ).select_related("variant__product")
        if variant := self.request.query_params.get("variant"):
            qs = qs.filter(variant_id=variant)
        return qs
