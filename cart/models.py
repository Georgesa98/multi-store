from django.db import models

from core.models import TimeStampedModel


class Cart(TimeStampedModel):
    """One cart per (customer, store); checkout consumes every store's cart."""

    customer = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="carts",
    )
    store = models.ForeignKey(
        "stores.Store",
        on_delete=models.CASCADE,
        related_name="+",
    )
    # `coupon` FK to orders.Coupon is added in cart.0002, once orders exists.
    coupon = models.ForeignKey(
        "orders.Coupon",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta(TimeStampedModel.Meta):
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["customer", "store"], name="uniq_cart_per_customer_store"
            )
        ]
        indexes = [models.Index(fields=["customer"])]

    def __str__(self):
        return f"Cart {self.customer_id} @ {self.store_id}"


class CartItem(TimeStampedModel):
    cart = models.ForeignKey(
        "cart.Cart",
        on_delete=models.CASCADE,
        related_name="items",
    )
    variant = models.ForeignKey(
        "catalog.ProductVariant",
        on_delete=models.PROTECT,
        related_name="+",
    )
    quantity = models.PositiveIntegerField(default=1)

    class Meta(TimeStampedModel.Meta):
        ordering = ("created_at",)
        constraints = [
            models.UniqueConstraint(fields=["cart", "variant"], name="uniq_item_per_cart"),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="cart_item_quantity_positive"
            ),
        ]
        indexes = [models.Index(fields=["cart"])]

    def __str__(self):
        return f"{self.quantity} x {self.variant_id}"
