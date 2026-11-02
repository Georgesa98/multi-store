"""Cart rules: one cart per store, stock aware, coupon validated up front."""

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from cart.models import Cart, CartItem
from core.enums import CouponType, ProductStatus
from core.exceptions import BusinessRuleViolation
from core.money import money
from orders.models import Coupon


def get_or_create_cart(*, customer, store) -> Cart:
    cart, _ = Cart.objects.get_or_create(customer=customer, store=store)
    return cart


def cart_subtotal(cart: Cart) -> Decimal:
    total = Decimal("0")
    for item in cart.items.select_related("variant"):
        total += item.variant.price * item.quantity
    return money(total)


def coupon_discount(coupon: Coupon, subtotal: Decimal) -> Decimal:
    """Discount for `subtotal`, or 422 when the coupon cannot apply."""
    if not coupon.is_active:
        raise BusinessRuleViolation({"code": ["This coupon is not active."]})

    now = timezone.now()
    if coupon.starts_at and now < coupon.starts_at:
        raise BusinessRuleViolation({"code": ["This coupon is not valid yet."]})
    if coupon.ends_at and now > coupon.ends_at:
        raise BusinessRuleViolation({"code": ["This coupon has expired."]})
    if coupon.max_uses is not None and coupon.used_count >= coupon.max_uses:
        raise BusinessRuleViolation({"code": ["This coupon has been fully redeemed."]})
    if subtotal < coupon.min_order_total:
        raise BusinessRuleViolation(
            {"code": [f"This coupon needs a subtotal of at least {coupon.min_order_total}."]}
        )

    if coupon.discount_type == CouponType.PERCENT:
        discount = subtotal * coupon.value / Decimal("100")
    else:
        discount = coupon.value

    if coupon.max_discount is not None:
        discount = min(discount, coupon.max_discount)
    return money(max(min(discount, subtotal), Decimal("0")))


def find_coupon(*, code: str, store) -> Coupon | None:
    """Store-specific coupon wins over a platform-wide one with the same code."""
    coupons = Coupon.objects.filter(code__iexact=code)
    return coupons.filter(store=store).first() or coupons.filter(store__isnull=True).first()


def cart_discount(cart: Cart) -> Decimal:
    if cart.coupon_id is None:
        return Decimal("0")
    return coupon_discount(cart.coupon, cart_subtotal(cart))


@transaction.atomic
def add_item(*, cart: Cart, variant, quantity: int) -> CartItem:
    quantity = int(quantity)
    if quantity <= 0:
        raise BusinessRuleViolation({"quantity": ["Quantity must be at least 1."]})

    product = variant.product
    if product.store_id != cart.store_id:
        raise BusinessRuleViolation({"variant": ["That product is sold by another store."]})
    if not variant.is_active or product.status != ProductStatus.ACTIVE or not product.is_available:
        raise BusinessRuleViolation({"variant": ["That product is not available."]})
    if quantity > variant.stock_qty:
        raise BusinessRuleViolation({"quantity": [f"Only {variant.stock_qty} left in stock."]})

    item, created = CartItem.objects.get_or_create(
        cart=cart, variant=variant, defaults={"quantity": quantity}
    )
    if not created:
        new_quantity = item.quantity + quantity
        if new_quantity > variant.stock_qty:
            raise BusinessRuleViolation({"quantity": [f"Only {variant.stock_qty} left in stock."]})
        item.quantity = new_quantity
        item.save(update_fields=["quantity", "updated_at"])
    return item


@transaction.atomic
def update_item(*, item: CartItem, quantity: int) -> CartItem | None:
    quantity = int(quantity)
    if quantity <= 0:
        item.delete()
        return None
    if quantity > item.variant.stock_qty:
        raise BusinessRuleViolation({"quantity": [f"Only {item.variant.stock_qty} left in stock."]})
    item.quantity = quantity
    item.save(update_fields=["quantity", "updated_at"])
    return item


@transaction.atomic
def remove_item(item: CartItem) -> None:
    item.delete()


@transaction.atomic
def clear_cart(cart: Cart) -> None:
    cart.items.all().delete()
    cart.coupon = None
    cart.save(update_fields=["coupon", "updated_at"])


@transaction.atomic
def apply_coupon(*, cart: Cart, code: str) -> Cart:
    coupon = find_coupon(code=code, store=cart.store)
    if coupon is None:
        raise BusinessRuleViolation({"code": ["Coupon not found."]})
    # Validate against the current subtotal now, and again at checkout.
    coupon_discount(coupon, cart_subtotal(cart))
    cart.coupon = coupon
    cart.save(update_fields=["coupon", "updated_at"])
    return cart


@transaction.atomic
def remove_coupon(cart: Cart) -> Cart:
    cart.coupon = None
    cart.save(update_fields=["coupon", "updated_at"])
    return cart
