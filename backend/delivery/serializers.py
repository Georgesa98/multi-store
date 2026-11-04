"""Serializers for delivery companies, their teams, zones, jobs and couriers."""

from decimal import Decimal

from rest_framework import serializers

from core.enums import MemberRole, Vehicle
from delivery.models import (
    CompanyMembership,
    CourierLocation,
    Delivery,
    DeliveryCompany,
    DeliveryEvent,
    DeliveryZone,
    StoreDeliveryPartner,
)
from orders.serializers import OrderItemSerializer


class DeliveryCompanyBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeliveryCompany
        fields = ("id", "slug", "name", "phone", "status")
        read_only_fields = fields


class DeliveryCompanySerializer(serializers.ModelSerializer):
    owner_email = serializers.EmailField(source="owner.email", read_only=True)
    owner_full_name = serializers.CharField(source="owner.full_name", read_only=True)

    class Meta:
        model = DeliveryCompany
        fields = (
            "id",
            "slug",
            "name",
            "description",
            "phone",
            "address_text",
            "status",
            "logo",
            "cover",
            "lat",
            "lng",
            "commission_rate",
            "is_accepting_jobs",
            "suspended_reason",
            "owner_email",
            "owner_full_name",
            "created_at",
        )
        read_only_fields = (
            "id",
            "slug",
            "status",
            "commission_rate",
            "suspended_reason",
            "created_at",
        )


class DeliveryCompanyOnboardSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=160)
    slug = serializers.SlugField(max_length=80, required=False, allow_blank=True)
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


class CompanyMemberUserSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    email = serializers.EmailField(read_only=True)
    full_name = serializers.CharField(read_only=True)
    phone = serializers.CharField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)


class CompanyMembershipSerializer(serializers.ModelSerializer):
    user = CompanyMemberUserSerializer(read_only=True)

    class Meta:
        model = CompanyMembership
        fields = ("id", "user", "role", "is_active", "created_at")
        read_only_fields = ("id", "user", "created_at")


class CompanyMemberInviteSerializer(serializers.Serializer):
    email = serializers.EmailField()
    full_name = serializers.CharField(max_length=150)
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    role = serializers.ChoiceField(
        choices=(MemberRole.MANAGER, MemberRole.STAFF), default=MemberRole.MANAGER
    )


class CourierBriefSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    user_id = serializers.UUIDField(read_only=True)
    full_name = serializers.CharField(source="user.full_name", read_only=True)
    phone = serializers.CharField(source="user.phone", read_only=True)
    vehicle = serializers.CharField(read_only=True)
    plate = serializers.CharField(read_only=True)
    is_available = serializers.BooleanField(read_only=True)


class CourierSerializer(CourierBriefSerializer):
    avg_rating = serializers.DecimalField(max_digits=3, decimal_places=2, read_only=True)
    deliveries_count = serializers.IntegerField(read_only=True)
    is_active = serializers.BooleanField(source="user.is_active", read_only=True)


class CourierCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    full_name = serializers.CharField(max_length=150)
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    vehicle = serializers.ChoiceField(choices=Vehicle.choices, default=Vehicle.MOTORCYCLE)
    plate = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")


class CourierUpdateSerializer(serializers.Serializer):
    vehicle = serializers.ChoiceField(choices=Vehicle.choices, required=False)
    plate = serializers.CharField(max_length=20, required=False, allow_blank=True)
    is_available = serializers.BooleanField(required=False)
    is_active = serializers.BooleanField(required=False)


class CourierAvailabilitySerializer(serializers.Serializer):
    """The courier's own switch carries one field; vehicle and plate are the
    company's to set (`PATCH /company/couriers/{id}/`)."""

    is_available = serializers.BooleanField()


class DeliveryZoneSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeliveryZone
        fields = (
            "id",
            "name",
            "center_lat",
            "center_lng",
            "radius_km",
            "fee",
            "min_order_total",
            "eta_minutes",
            "is_active",
            "created_at",
        )
        read_only_fields = ("id", "created_at")
        extra_kwargs = {
            "radius_km": {"min_value": Decimal("0.01")},
            "fee": {"min_value": Decimal("0")},
            "min_order_total": {"min_value": Decimal("0")},
        }

    def validate(self, attrs):
        attrs = super().validate(attrs)
        company = self.context.get("company")
        name = attrs.get("name", getattr(self.instance, "name", None))
        if company is not None and name:
            clash = DeliveryZone.objects.filter(company=company, name=name)
            if self.instance is not None:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                raise serializers.ValidationError(
                    {"name": ["This company already has a zone with that name."]}
                )
        return attrs


class SuspendCompanySerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500)


class PartnerSerializer(serializers.ModelSerializer):
    company = DeliveryCompanyBriefSerializer(read_only=True)

    class Meta:
        model = StoreDeliveryPartner
        fields = ("id", "company", "priority", "is_active", "created_at")
        read_only_fields = ("id", "company", "created_at")


class PartnerCreateSerializer(serializers.Serializer):
    company_id = serializers.UUIDField()
    priority = serializers.IntegerField(min_value=0, required=False, default=0)


class PartnerUpdateSerializer(serializers.Serializer):
    priority = serializers.IntegerField(min_value=0, required=False)
    is_active = serializers.BooleanField(required=False)


class DeliveryCourierSerializer(serializers.Serializer):
    """The courier on a delivery is a `User`, not a profile."""

    id = serializers.UUIDField(read_only=True)
    full_name = serializers.CharField(read_only=True)
    phone = serializers.CharField(read_only=True)
    vehicle = serializers.CharField(source="courier_profile.vehicle", read_only=True)
    plate = serializers.CharField(source="courier_profile.plate", read_only=True)


class DeliverySummarySerializer(serializers.ModelSerializer):
    company = DeliveryCompanyBriefSerializer(read_only=True)
    courier = DeliveryCourierSerializer(read_only=True)

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
            "created_at",
        )
        read_only_fields = fields


class JobOrderSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    number = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    payment_method = serializers.CharField(read_only=True)
    payment_status = serializers.CharField(read_only=True)
    subtotal = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    delivery_fee = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    currency = serializers.CharField(read_only=True)
    customer_note = serializers.CharField(read_only=True)
    address_snapshot = serializers.JSONField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    items = OrderItemSerializer(many=True, read_only=True)


class JobStoreSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    slug = serializers.SlugField(read_only=True)
    name = serializers.CharField(read_only=True)
    phone = serializers.CharField(read_only=True)
    address_text = serializers.CharField(read_only=True)
    lat = serializers.DecimalField(max_digits=9, decimal_places=6, read_only=True)
    lng = serializers.DecimalField(max_digits=9, decimal_places=6, read_only=True)


class DeliveryJobSerializer(DeliverySummarySerializer):
    order = JobOrderSerializer(read_only=True)
    store = JobStoreSerializer(read_only=True)
    zone_name = serializers.CharField(source="zone.name", read_only=True)
    eta_minutes = serializers.IntegerField(source="zone.eta_minutes", read_only=True)

    class Meta(DeliverySummarySerializer.Meta):
        fields = DeliverySummarySerializer.Meta.fields + (
            "order",
            "store",
            "zone_name",
            "eta_minutes",
        )
        read_only_fields = fields


class DeliveryEventSerializer(serializers.ModelSerializer):
    actor_role = serializers.CharField(source="actor.role", read_only=True)

    class Meta:
        model = DeliveryEvent
        fields = (
            "id",
            "action",
            "from_courier",
            "to_courier",
            "from_company",
            "to_company",
            "actor",
            "actor_role",
            "note",
            "created_at",
        )
        read_only_fields = fields


class DeliveryJobDetailSerializer(DeliveryJobSerializer):
    events = DeliveryEventSerializer(many=True, read_only=True)

    class Meta(DeliveryJobSerializer.Meta):
        fields = DeliveryJobSerializer.Meta.fields + ("events",)
        read_only_fields = fields


class DeliveryAssignSerializer(serializers.Serializer):
    courier_id = serializers.UUIDField()


class DeliveryRequestSerializer(serializers.Serializer):
    company_id = serializers.UUIDField(required=False)
    note = serializers.CharField(required=False, allow_blank=True, default="")


class DeliveryReleaseSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, default="")


class DeliveryDeliverSerializer(serializers.Serializer):
    otp = serializers.CharField(max_length=12, required=False, allow_blank=True, default="")
    note = serializers.CharField(required=False, allow_blank=True, default="")
    proof_photo = serializers.ImageField(required=False, allow_null=True)


class DeliveryFailSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500)


class DeliveryLocationSerializer(serializers.Serializer):
    lat = serializers.DecimalField(max_digits=9, decimal_places=6)
    lng = serializers.DecimalField(max_digits=9, decimal_places=6)
    accuracy_m = serializers.DecimalField(
        max_digits=6, decimal_places=2, required=False, allow_null=True
    )
    heading = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, allow_null=True
    )


class CourierLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = CourierLocation
        fields = ("lat", "lng", "accuracy_m", "heading", "is_online", "updated_at")
        read_only_fields = fields


class TrackingTicketSerializer(serializers.Serializer):
    ticket = serializers.CharField(read_only=True)
    expires_in = serializers.IntegerField(read_only=True)
    url = serializers.CharField(read_only=True)


class EarningsSerializer(serializers.Serializer):
    deliveries = serializers.IntegerField(read_only=True)
    cash_collected = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    gross_fees = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True, required=False
    )
    platform_commission = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True, required=False
    )
    net_fees = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True, required=False
    )
    delivery_fees = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True, required=False
    )
