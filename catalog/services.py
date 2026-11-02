"""Catalogue business logic: products, variants, stock, images."""

from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.utils.text import slugify

from catalog.models import InventoryMovement, Product, ProductImage, ProductVariant
from core.enums import InventoryReason, ProductStatus
from core.exceptions import BusinessRuleViolation, Conflict

# Only these can be posted by a human from the dashboard; `sale` and
# `cancel_return` are written by the order flow.
MANUAL_REASONS = {InventoryReason.RESTOCK, InventoryReason.MANUAL, InventoryReason.DAMAGE}


def _unique_slug(model, store, base: str) -> str:
    base = slugify(base)[:180] or "product"
    candidate = base
    i = 2
    while model.objects.filter(store=store, slug=candidate).exists():
        candidate = f"{base}-{i}"
        i += 1
    return candidate


def _unique_sku(product, label: str) -> str:
    base = f"{product.store.slug[:12]}-{product.slug[:30]}-{slugify(label)[:12] or 'sku'}"
    candidate = base.upper()
    i = 2
    while ProductVariant.objects.filter(sku=candidate).exists():
        candidate = f"{base.upper()}-{i}"
        i += 1
    return candidate


@transaction.atomic
def create_product(
    *,
    store,
    name,
    slug="",
    category=None,
    description="",
    status=ProductStatus.DRAFT,
    is_available=True,
    price=None,
    stock_qty=0,
    actor=None,
):
    if category is not None and category.store_id not in (None, store.id):
        raise BusinessRuleViolation({"category": ["That category belongs to another store."]})

    product = Product.objects.create(
        store=store,
        name=name,
        slug=slug or _unique_slug(Product, store, name),
        category=category,
        description=description,
        status=status,
        is_available=is_available,
    )

    if price is not None:
        variant = add_variant(
            product=product,
            label="Default",
            price=price,
            stock_qty=int(stock_qty or 0),
            actor=actor,
        )
        return product, variant
    return product, None


@transaction.atomic
def update_product(product, **fields) -> Product:
    allowed = {"name", "description", "status", "is_available", "category", "slug"}
    for key, value in fields.items():
        if key in allowed:
            setattr(product, key, value)
    if product.category_id and product.category.store_id not in (None, product.store_id):
        raise BusinessRuleViolation({"category": ["That category belongs to another store."]})
    product.save()
    return product


@transaction.atomic
def archive_product(product) -> Product:
    """Delete is archive: products on orders must never disappear."""
    product.status = ProductStatus.ARCHIVED
    product.is_available = False
    product.save(update_fields=["status", "is_available", "updated_at"])
    product.variants.update(is_active=False)
    return product


@transaction.atomic
def add_variant(
    *,
    product,
    price,
    label="Default",
    compare_at_price=None,
    stock_qty=0,
    sku="",
    is_active=True,
    actor=None,
):
    if ProductVariant.objects.filter(product=product, label=label).exists():
        raise Conflict({"label": ["This product already has a variant with that label."]})

    price = Decimal(price)
    if price < 0:
        raise BusinessRuleViolation({"price": ["Price cannot be negative."]})

    variant = ProductVariant.objects.create(
        product=product,
        sku=sku or _unique_sku(product, label),
        label=label,
        price=price,
        compare_at_price=compare_at_price,
        stock_qty=0,
        is_active=is_active,
    )
    if stock_qty:
        adjust_stock(
            variant=variant,
            delta=int(stock_qty),
            reason=InventoryReason.RESTOCK,
            note="Initial stock",
            actor=actor,
        )
    return variant


@transaction.atomic
def update_variant(variant, **fields):
    """Only price, compare-at price, label and activation are editable."""
    allowed = {"price", "compare_at_price", "label", "is_active"}
    for key, value in fields.items():
        if key in allowed:
            setattr(variant, key, value)
    variant.save()
    return variant


def adjust_stock(
    *, variant, delta: int, reason: str, note="", actor=None, order=None, system=False
):
    """The only path that mutates stock. Append-only movement, in-transaction.

    Dashboard users may only post `restock`/`manual`/`damage`; the order flow
    passes `system=True` for `sale` and `cancel_return`.
    """
    delta = int(delta)
    if delta == 0:
        raise BusinessRuleViolation({"delta": ["Delta cannot be zero."]})
    if not system and reason not in MANUAL_REASONS:
        raise BusinessRuleViolation({"reason": ["This reason is system-only."]})

    with transaction.atomic():
        locked = ProductVariant.objects.select_for_update().get(pk=variant.pk)
        new_qty = locked.stock_qty + delta
        if new_qty < 0:
            raise BusinessRuleViolation(
                {"delta": [f"Stock would drop below zero (available: {locked.stock_qty})."]}
            )
        locked.stock_qty = new_qty
        locked.save(update_fields=["stock_qty", "updated_at"])

        movement = InventoryMovement.objects.create(
            variant=locked,
            delta=delta,
            reason=reason,
            note=note,
            created_by=actor,
            order=order,
        )

    variant.refresh_from_db(fields=["stock_qty"])
    return movement


@transaction.atomic
def add_image(*, product, image, alt="", sort_order=0) -> ProductImage:
    return ProductImage.objects.create(product=product, image=image, alt=alt, sort_order=sort_order)


@transaction.atomic
def bump_sold_count(product, quantity: int) -> None:
    Product.objects.filter(pk=product.pk).update(sold_count=F("sold_count") + quantity)
