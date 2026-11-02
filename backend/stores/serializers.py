from django.contrib.auth import get_user_model
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.enums import MemberRole, StoreStatus
from stores.models import OpeningHours, Store, StoreMembership

User = get_user_model()


class StoreDashboardSerializer(serializers.ModelSerializer):
    """Own-store read/update. Status, slug, currency and commission are platform-run."""

    is_open = serializers.BooleanField(read_only=True)

    class Meta:
        model = Store
        fields = (
            "id",
            "slug",
            "code",
            "name",
            "description",
            "phone",
            "address_text",
            "status",
            "logo",
            "cover",
            "lat",
            "lng",
            "currency",
            "commission_rate",
            "is_accepting_orders",
            "is_open",
            "created_at",
        )
        read_only_fields = (
            "id",
            "slug",
            "code",
            "status",
            "currency",
            "commission_rate",
            "created_at",
        )


class OpeningHoursSerializer(serializers.ModelSerializer):
    class Meta:
        model = OpeningHours
        fields = ("id", "weekday", "open_time", "close_time", "is_closed")
        read_only_fields = ("id",)
        extra_kwargs = {"is_closed": {"required": False}}

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if not attrs.get("is_closed", False):
            open_time = attrs.get("open_time")
            close_time = attrs.get("close_time")
            if open_time and close_time and close_time <= open_time:
                raise serializers.ValidationError(
                    {"close_time": ["Closing time must be after opening time."]}
                )
        return attrs


class OpeningHoursBulkSerializer(serializers.Serializer):
    hours = OpeningHoursSerializer(many=True)

    def validate_hours(self, rows):
        weekdays = [row["weekday"] for row in rows]
        if len(weekdays) != len(set(weekdays)):
            raise serializers.ValidationError("Each weekday may appear only once.")
        return rows


class DeliveryQuoteSerializer(serializers.Serializer):
    lat = serializers.DecimalField(max_digits=9, decimal_places=6)
    lng = serializers.DecimalField(max_digits=9, decimal_places=6)


class UserBriefSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    email = serializers.EmailField(read_only=True)
    full_name = serializers.CharField(read_only=True)
    phone = serializers.CharField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)


class StoreMembershipSerializer(serializers.ModelSerializer):
    user = UserBriefSerializer(read_only=True)

    class Meta:
        model = StoreMembership
        fields = ("id", "user", "role", "is_active")
        read_only_fields = ("id", "user", "role", "is_active")


class StoreOnboardSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=160)
    slug = serializers.SlugField(max_length=80, required=False, allow_blank=True)
    code = serializers.CharField(
        max_length=8,
        required=False,
        allow_blank=True,
        help_text="Order-number prefix, e.g. PIZ. Derived from the name when omitted.",
    )
    description = serializers.CharField(required=False, allow_blank=True, default="")
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    address_text = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default=""
    )
    lat = serializers.DecimalField(
        max_digits=9, decimal_places=6, required=False, allow_null=True, default=None
    )
    lng = serializers.DecimalField(
        max_digits=9, decimal_places=6, required=False, allow_null=True, default=None
    )
    owner_email = serializers.EmailField()
    owner_full_name = serializers.CharField(max_length=150)
    owner_phone = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    commission_rate = serializers.DecimalField(max_digits=5, decimal_places=4, required=False)


class StorePlatformSerializer(serializers.ModelSerializer):
    owner_email = serializers.EmailField(source="owner.email", read_only=True)
    owner_full_name = serializers.CharField(source="owner.full_name", read_only=True)
    members = StoreMembershipSerializer(source="memberships", many=True, read_only=True)

    class Meta:
        model = Store
        fields = (
            "id",
            "slug",
            "code",
            "name",
            "description",
            "phone",
            "address_text",
            "status",
            "lat",
            "lng",
            "currency",
            "commission_rate",
            "is_accepting_orders",
            "suspended_reason",
            "owner_email",
            "owner_full_name",
            "members",
            "created_at",
        )


class StoreStatusFilterSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=StoreStatus.choices, required=False)


class SuspendStoreSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500)


class StorePublicSerializer(serializers.ModelSerializer):
    is_open = serializers.BooleanField(read_only=True)

    class Meta:
        model = Store
        fields = (
            "id",
            "slug",
            "name",
            "description",
            "address_text",
            "logo",
            "cover",
            "lat",
            "lng",
            "currency",
            "is_open",
        )


class PublicCompanySerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    slug = serializers.SlugField(read_only=True)
    name = serializers.CharField(read_only=True)


class StorePublicDetailSerializer(StorePublicSerializer):
    opening_hours = OpeningHoursSerializer(many=True, read_only=True)
    delivery_companies = serializers.SerializerMethodField()

    class Meta(StorePublicSerializer.Meta):
        fields = StorePublicSerializer.Meta.fields + (
            "phone",
            "opening_hours",
            "delivery_companies",
        )

    @extend_schema_field(PublicCompanySerializer(many=True))
    def get_delivery_companies(self, obj):
        partners = obj.delivery_partners.filter(
            is_active=True, company__status="active"
        ).select_related("company")
        return [
            {
                "id": str(partner.company_id),
                "slug": partner.company.slug,
                "name": partner.company.name,
            }
            for partner in partners
        ]


class MemberRoleSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=MemberRole.choices, read_only=True)
