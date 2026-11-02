"""Insight and ledger payloads. Money stays a string, counts stay integers."""

from rest_framework import serializers

from analytics.models import LedgerEntry, Payout


class MoneyField(serializers.DecimalField):
    def __init__(self, **kwargs):
        kwargs.setdefault("max_digits", 14)
        kwargs.setdefault("decimal_places", 2)
        super().__init__(**kwargs)


class InsightSummarySerializer(serializers.Serializer):
    from_date = serializers.DateField(read_only=True)
    to_date = serializers.DateField(read_only=True)
    orders = serializers.IntegerField(read_only=True)
    orders_delivered = serializers.IntegerField(read_only=True)
    orders_cancelled = serializers.IntegerField(read_only=True)
    new_customers = serializers.IntegerField(read_only=True)
    gross_sales = MoneyField(read_only=True)
    net_sales = MoneyField(read_only=True)
    delivery_fees = MoneyField(read_only=True)
    discounts = MoneyField(read_only=True)
    refunds = MoneyField(read_only=True)
    aov = MoneyField(read_only=True)


class DailyStoreStatSerializer(serializers.Serializer):
    date = serializers.DateField(read_only=True)
    orders_placed = serializers.IntegerField(read_only=True)
    orders_delivered = serializers.IntegerField(read_only=True)
    orders_cancelled = serializers.IntegerField(read_only=True)
    new_customers = serializers.IntegerField(read_only=True)
    gross_sales = MoneyField(read_only=True)
    net_sales = MoneyField(read_only=True)
    delivery_fees = MoneyField(read_only=True)
    discounts = MoneyField(read_only=True)
    refunds = MoneyField(read_only=True)


class TopProductSerializer(serializers.Serializer):
    product_id = serializers.UUIDField(read_only=True, allow_null=True)
    name = serializers.CharField(read_only=True)
    qty_sold = serializers.IntegerField(read_only=True)
    revenue = MoneyField(read_only=True)


class OrdersByStatusSerializer(serializers.Serializer):
    status = serializers.CharField(read_only=True)
    count = serializers.IntegerField(read_only=True)


class DeliveryPerformanceSerializer(serializers.Serializer):
    completed = serializers.IntegerField(read_only=True)
    failed = serializers.IntegerField(read_only=True)
    avg_minutes = MoneyField(read_only=True)
    failure_rate = serializers.DecimalField(max_digits=5, decimal_places=4, read_only=True)


class PlatformOverviewSerializer(serializers.Serializer):
    from_date = serializers.DateField(read_only=True)
    to_date = serializers.DateField(read_only=True)
    orders = serializers.IntegerField(read_only=True)
    gmv = MoneyField(read_only=True)
    active_stores = serializers.IntegerField(read_only=True)
    active_companies = serializers.IntegerField(read_only=True)


class PlatformRevenueSerializer(serializers.Serializer):
    date = serializers.DateField(read_only=True)
    gross = MoneyField(read_only=True)
    commission = MoneyField(read_only=True)
    net = MoneyField(read_only=True)


class PayoutSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source="store.name", read_only=True)
    company_name = serializers.CharField(source="company.name", read_only=True)

    class Meta:
        model = Payout
        fields = (
            "id",
            "store",
            "store_name",
            "company",
            "company_name",
            "period_start",
            "period_end",
            "deliveries",
            "cash_collected",
            "delivery_fees",
            "platform_commission",
            "store_net",
            "company_net",
            "status",
            "settled_at",
            "paid_at",
            "created_at",
        )
        read_only_fields = fields


class LedgerEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = LedgerEntry
        fields = (
            "id",
            "kind",
            "gross",
            "commission",
            "net",
            "order",
            "delivery",
            "created_at",
        )
        read_only_fields = fields
