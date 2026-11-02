from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from cart import services
from cart.models import Cart, CartItem
from core.exceptions import BusinessRuleViolation
from core.money import money_str
from orders.serializers import CouponBriefSerializer, StoreBriefSerializer


class CartVariantSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    sku = serializers.CharField(read_only=True)
    label = serializers.CharField(read_only=True)
    price = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    compare_at_price = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True, allow_null=True
    )
    stock_qty = serializers.IntegerField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    product = serializers.UUIDField(source="product_id", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_slug = serializers.SlugField(source="product.slug", read_only=True)
    image = serializers.SerializerMethodField()

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_image(self, obj):
        image = next(iter(obj.product.images.all()), None)
        if image is None or not image.image:
            return None
        request = self.context.get("request")
        url = image.image.url
        return request.build_absolute_uri(url) if request else url


class CartItemSerializer(serializers.ModelSerializer):
    variant = CartVariantSerializer(read_only=True)
    line_total = serializers.SerializerMethodField()

    class Meta:
        model = CartItem
        fields = ("id", "variant", "quantity", "line_total", "created_at")
        read_only_fields = ("id", "line_total", "created_at")

    @extend_schema_field(serializers.DecimalField(max_digits=12, decimal_places=2))
    def get_line_total(self, obj):
        return money_str(obj.variant.price * obj.quantity)


class CartSerializer(serializers.ModelSerializer):
    store = StoreBriefSerializer(read_only=True)
    items = CartItemSerializer(many=True, read_only=True)
    coupon = CouponBriefSerializer(read_only=True, allow_null=True)
    subtotal = serializers.SerializerMethodField()
    discount_total = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()

    class Meta:
        model = Cart
        fields = (
            "id",
            "store",
            "items",
            "coupon",
            "subtotal",
            "discount_total",
            "total",
            "created_at",
        )
        read_only_fields = fields

    @extend_schema_field(serializers.DecimalField(max_digits=12, decimal_places=2))
    def get_subtotal(self, obj):
        return money_str(services.cart_subtotal(obj))

    @extend_schema_field(serializers.DecimalField(max_digits=12, decimal_places=2))
    def get_discount_total(self, obj):
        try:
            return money_str(services.cart_discount(obj))
        except BusinessRuleViolation:
            return "0.00"

    @extend_schema_field(serializers.DecimalField(max_digits=12, decimal_places=2))
    def get_total(self, obj):
        try:
            discount = services.cart_discount(obj)
        except BusinessRuleViolation:
            discount = 0
        return money_str(services.cart_subtotal(obj) - discount)


class CartCreateSerializer(serializers.Serializer):
    store = serializers.UUIDField()


class AddItemSerializer(serializers.Serializer):
    variant = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1, default=1)


class UpdateItemSerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=0)


class ApplyCouponSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=40)
