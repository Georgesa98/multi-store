from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from catalog.models import Category, InventoryMovement, Product, ProductImage, ProductVariant
from core.enums import InventoryReason, ProductStatus


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ("id", "parent", "name", "slug", "sort_order", "is_active")
        read_only_fields = ("id",)
        extra_kwargs = {"slug": {"required": False}, "parent": {"required": False}}

    def validate_parent(self, parent):
        store = self.context.get("store")
        if parent is not None and store is not None and parent.store_id != store.id:
            raise serializers.ValidationError("Parent category belongs to another store.")
        return parent


class ProductImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields = ("id", "image", "alt", "sort_order", "created_at")
        read_only_fields = ("id", "created_at")


class ProductVariantSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductVariant
        fields = (
            "id",
            "sku",
            "label",
            "price",
            "compare_at_price",
            "stock_qty",
            "is_active",
        )
        read_only_fields = ("id", "sku", "stock_qty")


class ProductVariantWriteSerializer(serializers.ModelSerializer):
    """Price, label and activation only — stock has its own endpoint."""

    class Meta:
        model = ProductVariant
        fields = ("id", "label", "price", "compare_at_price", "is_active")
        read_only_fields = ("id",)


class VariantCreateSerializer(serializers.Serializer):
    label = serializers.CharField(max_length=60, default="Default")
    price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0)
    compare_at_price = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, allow_null=True, default=None
    )
    stock_qty = serializers.IntegerField(min_value=0, default=0)
    sku = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    is_active = serializers.BooleanField(required=False, default=True)


class StockAdjustSerializer(serializers.Serializer):
    delta = serializers.IntegerField()
    reason = serializers.ChoiceField(choices=InventoryReason.choices)
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")

    def validate_reason(self, value):
        allowed = {
            InventoryReason.RESTOCK,
            InventoryReason.MANUAL,
            InventoryReason.DAMAGE,
        }
        if value not in allowed:
            raise serializers.ValidationError("This reason can only be set by the order flow.")
        return value


class ProductDashboardSerializer(serializers.ModelSerializer):
    images = ProductImageSerializer(many=True, read_only=True)
    variants = ProductVariantSerializer(many=True, read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True)

    class Meta:
        model = Product
        fields = (
            "id",
            "category",
            "category_name",
            "name",
            "slug",
            "description",
            "status",
            "is_available",
            "avg_rating",
            "rating_count",
            "sold_count",
            "images",
            "variants",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "avg_rating",
            "rating_count",
            "sold_count",
            "created_at",
            "updated_at",
        )
        extra_kwargs = {"slug": {"required": False}}


class ProductCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    slug = serializers.SlugField(max_length=200, required=False, allow_blank=True, default="")
    category = serializers.UUIDField(required=False, allow_null=True, default=None)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    status = serializers.ChoiceField(
        choices=ProductStatus.choices, required=False, default=ProductStatus.DRAFT
    )
    is_available = serializers.BooleanField(required=False, default=True)
    price = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=0, required=False, allow_null=True, default=None
    )
    stock_qty = serializers.IntegerField(min_value=0, required=False, default=0)


class ProductUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ("name", "slug", "category", "description", "status", "is_available")
        extra_kwargs = {"slug": {"required": False}}


class PublicImageSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    url = serializers.CharField(read_only=True)
    alt = serializers.CharField(read_only=True)


class ProductPublicSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()
    price = serializers.SerializerMethodField()
    compare_at_price = serializers.SerializerMethodField()
    in_stock = serializers.SerializerMethodField()
    category_slug = serializers.CharField(source="category.slug", read_only=True)

    class Meta:
        model = Product
        fields = (
            "id",
            "name",
            "slug",
            "category_slug",
            "image",
            "price",
            "compare_at_price",
            "in_stock",
            "avg_rating",
            "rating_count",
            "sold_count",
            "is_available",
        )

    def _variants(self, obj):
        return [v for v in obj.variants.all() if v.is_active]

    def _first(self, obj):
        variants = self._variants(obj)
        return min(variants, key=lambda v: v.price) if variants else None

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_image(self, obj):
        images = list(obj.images.all())
        if not images:
            return None
        request = self.context.get("request")
        url = images[0].image.url
        return request.build_absolute_uri(url) if request else url

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_price(self, obj):
        variant = self._first(obj)
        return f"{variant.price:.2f}" if variant else None

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_compare_at_price(self, obj):
        variant = self._first(obj)
        if variant is None or variant.compare_at_price is None:
            return None
        return f"{variant.compare_at_price:.2f}"

    @extend_schema_field(serializers.BooleanField)
    def get_in_stock(self, obj):
        return any(v.stock_qty > 0 for v in self._variants(obj))


class ProductPublicDetailSerializer(ProductPublicSerializer):
    variants = serializers.SerializerMethodField()
    images = serializers.SerializerMethodField()

    class Meta(ProductPublicSerializer.Meta):
        fields = ProductPublicSerializer.Meta.fields + ("description", "variants", "images")

    @extend_schema_field(ProductVariantSerializer(many=True))
    def get_variants(self, obj):
        return ProductVariantSerializer(self._variants(obj), many=True).data

    @extend_schema_field(PublicImageSerializer(many=True))
    def get_images(self, obj):
        request = self.context.get("request")
        out = []
        for image in obj.images.all():
            url = image.image.url
            out.append(
                {
                    "id": str(image.id),
                    "url": request.build_absolute_uri(url) if request else url,
                    "alt": image.alt,
                }
            )
        return out


class InventoryMovementSerializer(serializers.ModelSerializer):
    variant_label = serializers.CharField(source="variant.label", read_only=True)
    product_name = serializers.CharField(source="variant.product.name", read_only=True)

    class Meta:
        model = InventoryMovement
        fields = (
            "id",
            "variant",
            "variant_label",
            "product_name",
            "delta",
            "reason",
            "note",
            "created_by",
            "created_at",
        )
        read_only_fields = fields
