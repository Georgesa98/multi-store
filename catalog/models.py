from django.db import models
from django.utils.text import slugify

from core.enums import ProductStatus
from core.models import StoreScopedModel, TimeStampedModel


class Category(TimeStampedModel):
    """`store` null means platform-wide; otherwise a store's own category."""

    store = models.ForeignKey(
        "stores.Store",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="categories",
    )
    parent = models.ForeignKey(
        "catalog.Category",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
    )
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=120)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta(TimeStampedModel.Meta):
        ordering = ("sort_order", "name")
        verbose_name_plural = "categories"
        indexes = [models.Index(fields=["store", "is_active"])]
        constraints = [
            # Postgres treats NULLs as distinct, so the plain unique_together
            # the brief lists would allow duplicate platform categories.
            models.UniqueConstraint(
                fields=["store", "slug"],
                condition=models.Q(store__isnull=False),
                name="uniq_category_slug_per_store",
            ),
            models.UniqueConstraint(
                fields=["slug"],
                condition=models.Q(store__isnull=True),
                name="uniq_category_slug_platform",
            ),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:120]
        super().save(*args, **kwargs)


class Product(StoreScopedModel):
    category = models.ForeignKey(
        "catalog.Category",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=ProductStatus.choices, default=ProductStatus.DRAFT
    )
    is_available = models.BooleanField(default=True)
    avg_rating = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    rating_count = models.PositiveIntegerField(default=0)
    sold_count = models.PositiveIntegerField(default=0)

    class Meta(StoreScopedModel.Meta):
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(fields=["store", "slug"], name="uniq_product_slug_per_store")
        ]
        indexes = [
            models.Index(fields=["store", "status"]),
            models.Index(fields=["store", "is_available"]),
            models.Index(fields=["category"]),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:200]
        super().save(*args, **kwargs)


class ProductImage(TimeStampedModel):
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.CASCADE,
        related_name="images",
    )
    image = models.ImageField(upload_to="catalog/products/")
    sort_order = models.PositiveIntegerField(default=0)
    alt = models.CharField(max_length=160, blank=True)

    class Meta(TimeStampedModel.Meta):
        ordering = ("sort_order", "created_at")
        indexes = [models.Index(fields=["product", "sort_order"])]

    def __str__(self):
        return f"Image for {self.product_id}"


class ProductVariant(TimeStampedModel):
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.CASCADE,
        related_name="variants",
    )
    sku = models.CharField(max_length=64, unique=True)
    label = models.CharField(max_length=60, default="Default")
    price = models.DecimalField(max_digits=12, decimal_places=2)
    compare_at_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    stock_qty = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta(TimeStampedModel.Meta):
        ordering = ("label",)
        constraints = [
            models.UniqueConstraint(fields=["product", "label"], name="uniq_variant_label"),
            models.CheckConstraint(condition=models.Q(price__gte=0), name="variant_price_gte_0"),
            models.CheckConstraint(
                condition=models.Q(stock_qty__gte=0),
                name="variant_stock_gte_0",
            ),
        ]
        indexes = [models.Index(fields=["product", "is_active"])]

    def __str__(self):
        return f"{self.product_id} / {self.label}"


class InventoryMovement(TimeStampedModel):
    """Append-only. Every stock change writes exactly one row, in-transaction."""

    variant = models.ForeignKey(
        "catalog.ProductVariant",
        on_delete=models.PROTECT,
        related_name="movements",
    )
    delta = models.IntegerField()
    reason = models.CharField(max_length=20)  # core.enums.InventoryReason
    # `order` FK is added in Phase 2, when the orders app exists.
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    note = models.CharField(max_length=255, blank=True)

    class Meta(TimeStampedModel.Meta):
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["variant", "created_at"])]

    def __str__(self):
        return f"{self.variant_id}: {self.delta:+d} ({self.reason})"
