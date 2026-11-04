from decimal import Decimal

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.enums import CouponType, OrderStatus
from delivery.models import Delivery
from orders.models import (
    CheckoutGroup,
    Coupon,
    Order,
    OrderItem,
    OrderSequence,
    OrderStatusEvent,
)


class StoreBriefSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    slug = serializers.SlugField(read_only=True)
    code = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)


class CompanyBriefSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    slug = serializers.SlugField(read_only=True)
    name = serializers.CharField(read_only=True)


class ZoneBriefSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    fee = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    min_order_total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    eta_minutes = serializers.IntegerField(read_only=True)


class CouponBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Coupon
        fields = ("id", "code", "discount_type", "value")


class CustomerBriefSerializer(serializers.Serializer):
    """Who to call about this order. No email: it is account PII with no
    operational use on an order surface, and `/platform/users/` has it."""

    id = serializers.UUIDField(read_only=True)
    full_name = serializers.CharField(read_only=True)
    phone = serializers.CharField(read_only=True)


class CheckoutRequestSerializer(serializers.Serializer):
    address_id = serializers.UUIDField()
    store_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=True, default=list
    )
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class CheckoutStoreQuoteSerializer(serializers.Serializer):
    store = StoreBriefSerializer(read_only=True)
    cart_id = serializers.UUIDField(read_only=True)
    subtotal = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    delivery_fee = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    discount_total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    tax_total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    currency = serializers.CharField(read_only=True)
    company = CompanyBriefSerializer(read_only=True, allow_null=True)
    zone = ZoneBriefSerializer(read_only=True, allow_null=True)
    coupon = CouponBriefSerializer(read_only=True, allow_null=True)
    problems = serializers.ListField(child=serializers.CharField(), read_only=True)


class CheckoutPreviewSerializer(serializers.Serializer):
    stores = CheckoutStoreQuoteSerializer(many=True, read_only=True)
    problems = serializers.ListField(child=serializers.CharField(), read_only=True)


class OrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = (
            "id",
            "product",
            "variant",
            "name_snapshot",
            "variant_label_snapshot",
            "image_url_snapshot",
            "unit_price",
            "quantity",
            "line_total",
            "options_snapshot",
        )
        read_only_fields = fields


class OrderStatusEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderStatusEvent
        fields = (
            "id",
            "from_status",
            "to_status",
            "actor",
            "actor_role",
            "note",
            "created_at",
        )
        read_only_fields = fields


class OrderSummarySerializer(serializers.ModelSerializer):
    store = StoreBriefSerializer(read_only=True)
    customer = CustomerBriefSerializer(read_only=True)

    class Meta:
        model = Order
        fields = (
            "id",
            "number",
            "store",
            "customer",
            "status",
            "payment_method",
            "payment_status",
            "subtotal",
            "delivery_fee",
            "discount_total",
            "tax_total",
            "total",
            "currency",
            "created_at",
            "delivered_at",
            "cancelled_at",
            "cancel_reason",
        )
        read_only_fields = fields


class OrderDeliveryCourierSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    full_name = serializers.CharField(read_only=True)
    phone = serializers.CharField(read_only=True)


class OrderDeliverySerializer(serializers.ModelSerializer):
    company = CompanyBriefSerializer(read_only=True)
    courier = OrderDeliveryCourierSerializer(read_only=True)

    class Meta:
        model = Delivery
        fields = (
            "id",
            "status",
            "company",
            "courier",
            "fee",
            "cash_to_collect",
            "cash_collected",
            "cash_collected_at",
            "requested_at",
            "accepted_at",
            "picked_up_at",
            "delivered_at",
            "failed_at",
            "failure_reason",
        )
        read_only_fields = fields


class OrderDetailSerializer(OrderSummarySerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    events = OrderStatusEventSerializer(many=True, read_only=True)
    group = serializers.UUIDField(source="group_id", read_only=True)
    delivery = serializers.SerializerMethodField()

    class Meta(OrderSummarySerializer.Meta):
        fields = OrderSummarySerializer.Meta.fields + (
            "group",
            "address_snapshot",
            "customer_note",
            "items",
            "events",
            "delivery",
        )
        read_only_fields = fields

    @extend_schema_field(OrderDeliverySerializer(allow_null=True))
    def get_delivery(self, obj):
        delivery = getattr(obj, "delivery", None)
        if delivery is None:
            return None
        return OrderDeliverySerializer(delivery).data


class CheckoutGroupSerializer(serializers.ModelSerializer):
    orders = OrderSummarySerializer(many=True, read_only=True)

    class Meta:
        model = CheckoutGroup
        fields = (
            "id",
            "address_snapshot",
            "notes",
            "orders",
            "created_at",
        )
        read_only_fields = fields


class CancelOrderSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class OrderTransitionSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, default="")


class OrderSequenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderSequence
        fields = ("store", "last_number")
        read_only_fields = fields


class OrderStatusFilterSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=OrderStatus.choices, required=False)


class CouponSerializer(serializers.ModelSerializer):
    """Create/read/edit a coupon.

    The view pins the scope through `context["store"]`: a store dashboard pins
    its own store, the platform surface pins `None` (platform-wide).
    """

    class Meta:
        model = Coupon
        fields = (
            "id",
            "code",
            "discount_type",
            "value",
            "min_order_total",
            "max_discount",
            "starts_at",
            "ends_at",
            "max_uses",
            "used_count",
            "is_active",
            "created_at",
        )
        read_only_fields = ("id", "used_count", "created_at")
        extra_kwargs = {
            "value": {"min_value": Decimal("0")},
            "min_order_total": {"min_value": Decimal("0")},
            "max_discount": {"min_value": Decimal("0")},
        }

    def validate(self, attrs):
        instance = self.instance

        def current(field, default=None):
            if field in attrs:
                return attrs[field]
            return getattr(instance, field, default) if instance is not None else default

        discount_type = current("discount_type")
        value = current("value", Decimal("0"))
        if discount_type == CouponType.PERCENT and value is not None and value > 100:
            raise serializers.ValidationError({"value": ["A percent discount cannot exceed 100."]})

        starts_at, ends_at = current("starts_at"), current("ends_at")
        if starts_at and ends_at and ends_at <= starts_at:
            raise serializers.ValidationError({"ends_at": ["A coupon must end after it starts."]})

        code = current("code", "")
        store = self.context.get("store")
        duplicates = Coupon.objects.filter(code__iexact=code)
        duplicates = (
            duplicates.filter(store__isnull=True)
            if store is None
            else duplicates.filter(store=store)
        )
        if instance is not None:
            duplicates = duplicates.exclude(pk=instance.pk)
        if code and duplicates.exists():
            raise serializers.ValidationError({"code": ["This code is already in use."]})

        return attrs
