"""Review payloads: the customer writes, everyone reads, the store answers."""

from rest_framework import serializers

from reviews.models import Review


class ReviewSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.full_name", read_only=True)
    product_name = serializers.SerializerMethodField()

    class Meta:
        model = Review
        fields = (
            "id",
            "order_item",
            "rating",
            "comment",
            "store_reply",
            "replied_at",
            "customer_name",
            "product_name",
            "created_at",
        )
        read_only_fields = fields

    def get_product_name(self, obj) -> str:
        return obj.product.name if obj.product_id else ""


class ReviewCreateSerializer(serializers.Serializer):
    rating = serializers.IntegerField(min_value=1, max_value=5)
    comment = serializers.CharField(required=False, allow_blank=True, default="")


class ReviewReplySerializer(serializers.Serializer):
    reply = serializers.CharField()
