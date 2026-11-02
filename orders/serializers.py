from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.enums import OrderStatus
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
    id = serializers.UUIDField(read_only=True)
    email = serializers.EmailField(read_only=True)
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
