"""Public catalogue browsing for the customer app."""

from django.db.models import Prefetch, Q
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics
from rest_framework.permissions import AllowAny

from catalog.models import Category, Product, ProductImage, ProductVariant
from catalog.serializers import (
    CategorySerializer,
    ProductPublicDetailSerializer,
    ProductPublicSerializer,
)
from core.enums import ProductStatus, StoreStatus
from stores.models import Store


def _public_products(store):
    return (
        Product.objects.filter(
            store=store,
            status=ProductStatus.ACTIVE,
            is_available=True,
        )
        .select_related("category")
        .prefetch_related(
            Prefetch("variants", queryset=ProductVariant.objects.filter(is_active=True)),
            Prefetch("images", queryset=ProductImage.objects.order_by("sort_order")),
        )
        .order_by("name")
    )


def _visible_store_or_404(slug):
    return generics.get_object_or_404(Store, slug=slug, status=StoreStatus.ACTIVE)


@extend_schema(tags=["public"])
class PublicCategoryListView(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = CategorySerializer
    pagination_class = None

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Category.objects.none()
        store = _visible_store_or_404(self.kwargs["slug"])
        return Category.objects.filter(
            Q(store=store) | Q(store__isnull=True), is_active=True
        ).order_by("sort_order", "name")


@extend_schema(tags=["public"])
class PublicProductListView(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = ProductPublicSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter("category", str, description="Category slug"),
            OpenApiParameter("q", str),
            OpenApiParameter("min_price", float),
            OpenApiParameter("max_price", float),
            OpenApiParameter("in_stock", bool),
        ]
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Product.objects.none()
        store = _visible_store_or_404(self.kwargs["slug"])
        qs = _public_products(store)
        params = self.request.query_params

        if category := params.get("category"):
            qs = qs.filter(category__slug=category)
        if q := params.get("q"):
            qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q))
        if min_price := params.get("min_price"):
            qs = qs.filter(variants__is_active=True, variants__price__gte=min_price)
        if max_price := params.get("max_price"):
            qs = qs.filter(variants__is_active=True, variants__price__lte=max_price)
        if params.get("in_stock") in ("true", "1", "True"):
            qs = qs.filter(variants__is_active=True, variants__stock_qty__gt=0)

        return qs.distinct()


@extend_schema(tags=["public"])
class PublicProductDetailView(generics.RetrieveAPIView):
    permission_classes = [AllowAny]
    serializer_class = ProductPublicDetailSerializer
    lookup_field = "slug"

    def get_queryset(self):
        store = _visible_store_or_404(self.kwargs["store_slug"])
        return _public_products(store)

    def get_object(self):
        queryset = self.get_queryset()
        return generics.get_object_or_404(queryset, slug=self.kwargs["slug"])
