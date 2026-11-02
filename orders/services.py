"""Checkout, order numbering and the order state machine."""

from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from cart.models import Cart
from cart.services import cart_discount, cart_subtotal
from catalog import services as catalog_services
from core.enums import InventoryReason, OrderStatus, PaymentStatus, Role
from core.exceptions import BusinessRuleViolation, Conflict, InvalidTransition
from core.money import money
from notifications import services as notification_services
from orders.models import (
    CheckoutGroup,
    CouponRedemption,
    Order,
    OrderItem,
    OrderSequence,
    OrderStatusEvent,
)

TERMINAL_STATUSES = {
    OrderStatus.DELIVERED,
    OrderStatus.CANCELLED,
    OrderStatus.REFUNDED,
}

# (from, to) -> roles allowed to make the change. The generic super-admin
# rules are applied in `allowed_roles()` below.
TRANSITIONS: dict[tuple[str, str], set[str]] = {
    (OrderStatus.PENDING, OrderStatus.CONFIRMED): {Role.STORE_ADMIN, Role.SUPER_ADMIN},
    (OrderStatus.PENDING, OrderStatus.CANCELLED): {
        Role.CUSTOMER,
        Role.STORE_ADMIN,
        Role.SUPER_ADMIN,
    },
    (OrderStatus.CONFIRMED, OrderStatus.PREPARING): {Role.STORE_ADMIN, Role.SUPER_ADMIN},
    # §9.2 lets customers cancel while pending/confirmed; §7 omits them for
    # confirmed, so this row intentionally extends the table.
    (OrderStatus.CONFIRMED, OrderStatus.CANCELLED): {
        Role.CUSTOMER,
        Role.STORE_ADMIN,
        Role.SUPER_ADMIN,
    },
    (OrderStatus.PREPARING, OrderStatus.READY): {Role.STORE_ADMIN},
    (OrderStatus.PREPARING, OrderStatus.CANCELLED): {Role.STORE_ADMIN, Role.SUPER_ADMIN},
    # Entering `assigned` is the delivery company's act (dispatcher or courier
    # accepting an offer); the store may also do it manually.
    (OrderStatus.READY, OrderStatus.ASSIGNED): {
        Role.STORE_ADMIN,
        Role.DELIVERY_ADMIN,
        Role.COURIER,
        Role.SUPER_ADMIN,
    },
    (OrderStatus.READY, OrderStatus.CANCELLED): {Role.STORE_ADMIN, Role.SUPER_ADMIN},
    (OrderStatus.ASSIGNED, OrderStatus.OUT_FOR_DELIVERY): {
        Role.COURIER,
        Role.STORE_ADMIN,
        Role.DELIVERY_ADMIN,
    },
    # Release/reassign or a failed attempt sends the order back to `ready`.
    (OrderStatus.ASSIGNED, OrderStatus.READY): {
        Role.COURIER,
        Role.STORE_ADMIN,
        Role.DELIVERY_ADMIN,
        Role.SUPER_ADMIN,
    },
    (OrderStatus.OUT_FOR_DELIVERY, OrderStatus.READY): {
        Role.COURIER,
        Role.STORE_ADMIN,
        Role.DELIVERY_ADMIN,
        Role.SUPER_ADMIN,
    },
    (OrderStatus.OUT_FOR_DELIVERY, OrderStatus.DELIVERED): {
        Role.COURIER,
        Role.SUPER_ADMIN,
    },
    (OrderStatus.OUT_FOR_DELIVERY, OrderStatus.CANCELLED): {
        Role.COURIER,
        Role.SUPER_ADMIN,
    },
}


def allowed_roles(from_status: str, to_status: str) -> set[str]:
    if from_status in TERMINAL_STATUSES:
        return set()
    roles = set(TRANSITIONS.get((from_status, to_status), set()))
    if to_status == OrderStatus.CANCELLED:
        roles.add(Role.SUPER_ADMIN)
    if to_status == OrderStatus.REFUNDED:
        roles = {Role.SUPER_ADMIN}
    return roles


def address_snapshot(address) -> dict:
    if address is None:
        return {}
    return {
        "label": address.label,
        "line1": address.line1,
        "line2": address.line2,
        "city": address.city,
        "notes": address.notes,
        "lat": str(address.lat) if address.lat is not None else None,
        "lng": str(address.lng) if address.lng is not None else None,
    }


def allocate_order_number(store) -> str:
    """Per-store counter, locked so concurrent checkouts cannot collide."""
    seq = _lock_sequence(store)
    seq.last_number += 1
    seq.save(update_fields=["last_number", "updated_at"])
    return f"{store.code}-{seq.last_number:06d}"


def _lock_sequence(store) -> OrderSequence:
    try:
        return OrderSequence.objects.select_for_update().get(store=store)
    except OrderSequence.DoesNotExist:
        pass
    try:
        with transaction.atomic():
            return OrderSequence.objects.create(store=store)
    except IntegrityError:
        return OrderSequence.objects.select_for_update().get(store=store)


def quote_store(*, cart: Cart, address) -> dict:
    """Per-store subtotal/fee/discount/total plus any blocking problems.

    The delivery fee and coverage come from the company that serves this
    address for this store, never from the store itself.
    """
    from delivery.services import quote_for_store

    problems: list[str] = []
    subtotal = cart_subtotal(cart)
    discount = Decimal("0")

    if cart.coupon_id is not None:
        try:
            discount = cart_discount(cart)
        except BusinessRuleViolation as exc:
            problems.append(str(exc.detail))

    fee = Decimal("0")
    company = None
    zone = None
    if address is None or address.lat is None or address.lng is None:
        problems.append("A delivery address with coordinates is required.")
    else:
        quote = quote_for_store(cart.store, address.lat, address.lng)
        if quote is None:
            problems.append("No delivery company covers this address for this store.")
        else:
            company, zone = quote
            fee = zone.fee
            if subtotal < zone.min_order_total:
                problems.append(f"Minimum order for {zone.name} is {zone.min_order_total}.")

    total = money(subtotal + fee - discount)
    return {
        "store": cart.store,
        "cart_id": str(cart.id),
        "subtotal": subtotal,
        "delivery_fee": money(fee),
        "discount_total": money(discount),
        "tax_total": money(Decimal("0")),
        "total": total,
        "currency": cart.store.currency,
        "company": company,
        "zone": zone,
        "coupon": cart.coupon if cart.coupon_id else None,
        "problems": problems,
    }


def _carts_for(*, customer, store_ids=None):
    carts = (
        Cart.objects.filter(customer=customer)
        .select_related("store", "coupon")
        .prefetch_related("items__variant__product__images")
        .order_by("store__name")
    )
    if store_ids:
        carts = carts.filter(store_id__in=store_ids)
    return list(carts)


def preview(*, customer, address=None, store_ids=None) -> dict:
    rows = [
        quote_store(cart=cart, address=address)
        for cart in _carts_for(customer=customer, store_ids=store_ids)
    ]
    return {
        "stores": rows,
        "problems": [problem for row in rows for problem in row["problems"]],
    }


@transaction.atomic
def checkout(*, customer, address, store_ids=None, notes="", idempotency_key) -> CheckoutGroup:
    existing = CheckoutGroup.objects.filter(idempotency_key=idempotency_key).first()
    if existing is not None:
        return _replay(existing, customer)

    carts = _carts_for(customer=customer, store_ids=store_ids)
    if not carts:
        raise BusinessRuleViolation({"detail": "There is nothing to check out."})

    quotes = [quote_store(cart=cart, address=address) for cart in carts]
    problems = [problem for quote in quotes for problem in quote["problems"]]
    if problems:
        raise BusinessRuleViolation({"detail": problems})

    group = _create_group(
        customer=customer,
        address=address,
        notes=notes,
        idempotency_key=idempotency_key,
    )
    if group.customer_id != customer.id:  # concurrent replay by another customer
        raise Conflict({"detail": "That idempotency key was already used."})

    snapshot = address_snapshot(address)
    for cart, quote in zip(carts, quotes, strict=True):
        _create_order(
            group=group,
            cart=cart,
            quote=quote,
            customer=customer,
            snapshot=snapshot,
            notes=notes,
        )

    Cart.objects.filter(pk__in=[cart.pk for cart in carts]).delete()
    return group


def _replay(group: CheckoutGroup, customer) -> CheckoutGroup:
    if group.customer_id != customer.id:
        raise Conflict({"detail": "That idempotency key was already used."})
    return group


def _create_group(*, customer, address, notes, idempotency_key) -> CheckoutGroup:
    try:
        with transaction.atomic():
            return CheckoutGroup.objects.create(
                customer=customer,
                address_snapshot=address_snapshot(address),
                idempotency_key=idempotency_key,
                notes=notes,
            )
    except IntegrityError:
        return CheckoutGroup.objects.get(idempotency_key=idempotency_key)


def _create_order(*, group, cart, quote, customer, snapshot, notes) -> Order:
    store = cart.store
    order = Order.objects.create(
        store=store,
        group=group,
        customer=customer,
        number=allocate_order_number(store),
        status=OrderStatus.PENDING,
        payment_method="cod",
        payment_status=PaymentStatus.UNPAID,
        subtotal=quote["subtotal"],
        delivery_fee=quote["delivery_fee"],
        discount_total=quote["discount_total"],
        tax_total=quote["tax_total"],
        total=quote["total"],
        currency=store.currency,
        address_snapshot=snapshot,
        customer_note=notes,
    )

    for item in cart.items.select_related("variant__product").prefetch_related(
        "variant__product__images"
    ):
        variant = item.variant
        product = variant.product
        line_total = money(variant.price * item.quantity)
        OrderItem.objects.create(
            order=order,
            product=product,
            variant=variant,
            name_snapshot=product.name,
            variant_label_snapshot=variant.label,
            image_url_snapshot=_image_url(product),
            unit_price=variant.price,
            quantity=item.quantity,
            line_total=line_total,
            options_snapshot={},
        )
        catalog_services.adjust_stock(
            variant=variant,
            delta=-item.quantity,
            reason=InventoryReason.SALE,
            note=f"Order {order.number}",
            actor=customer,
            order=order,
            system=True,
        )

    if cart.coupon_id is not None and quote["discount_total"] > 0:
        CouponRedemption.objects.create(
            coupon=cart.coupon,
            customer=customer,
            order=order,
            discount_amount=quote["discount_total"],
        )
        type(cart.coupon).objects.filter(pk=cart.coupon_id).update(used_count=F("used_count") + 1)

    OrderStatusEvent.objects.create(
        order=order,
        from_status="",
        to_status=OrderStatus.PENDING,
        actor=customer,
        actor_role=customer.role,
        note="Order placed",
    )

    # The quoted company, zone and fee are locked in now: the store chose its
    # partners, the company quoted the address, and the customer accepted.
    from delivery.services import create_for_order

    create_for_order(
        order=order,
        company=quote["company"],
        zone=quote["zone"],
        fee=quote["delivery_fee"],
    )
    notification_services.order_placed(order)
    return order


def _image_url(product) -> str:
    image = next(iter(product.images.all()), None)
    if image is None or not image.image:
        return ""
    return image.image.url


@transaction.atomic
def transition(*, order, to_status: str, actor, note="", request_delivery=True) -> Order:
    order = Order.objects.select_for_update().get(pk=order.pk)
    from_status = order.status

    if from_status == to_status:
        raise Conflict({"detail": f"Order is already {to_status}."})

    roles = allowed_roles(from_status, to_status)
    if not roles:
        raise InvalidTransition(
            {"detail": f"Cannot move an order from {from_status} to {to_status}."}
        )
    if actor is None or getattr(actor, "role", None) not in roles:
        raise InvalidTransition(
            {"detail": f"Your role may not move an order from {from_status} to {to_status}."}
        )

    if to_status == OrderStatus.ASSIGNED:
        delivery = getattr(order, "delivery", None)
        if delivery is None or delivery.courier_id is None:
            raise BusinessRuleViolation(
                {"detail": "An order needs an assigned courier before it can be assigned."}
            )

    now = timezone.now()
    update_fields = ["status", "updated_at"]
    order.status = to_status

    if to_status == OrderStatus.DELIVERED:
        order.payment_status = PaymentStatus.COLLECTED
        order.delivered_at = now
        update_fields += ["payment_status", "delivered_at"]
    elif to_status == OrderStatus.CANCELLED:
        order.cancelled_at = now
        order.cancel_reason = note
        update_fields += ["cancelled_at", "cancel_reason"]
        _restore_stock(order, actor=actor)
    elif to_status == OrderStatus.REFUNDED:
        # COD cash was collected and the goods are with the customer: stock is
        # not restored and payment_status is left as-is; a compensating ledger
        # row is written in Phase 4.
        pass

    order.save(update_fields=update_fields)
    OrderStatusEvent.objects.create(
        order=order,
        from_status=from_status,
        to_status=to_status,
        actor=actor,
        actor_role=getattr(actor, "role", "") or "",
        note=note,
    )

    delivery = getattr(order, "delivery", None)
    if delivery is not None:
        from delivery import services as delivery_services

        if to_status == OrderStatus.READY and request_delivery:
            # A ready order is offered to the contracted delivery company.
            delivery_services.request_delivery(delivery, actor=actor)
        elif to_status in (OrderStatus.CANCELLED, OrderStatus.REFUNDED):
            delivery_services.cancel_delivery(delivery, actor=actor, note=note)

    notification_services.order_status_changed(order, from_status, to_status)
    return order


def _restore_stock(order: Order, *, actor) -> None:
    for item in order.items.select_related("variant"):
        if item.variant_id is None:
            continue
        catalog_services.adjust_stock(
            variant=item.variant,
            delta=item.quantity,
            reason=InventoryReason.CANCEL_RETURN,
            note=f"Order {order.number} cancelled",
            actor=actor,
            order=order,
            system=True,
        )


def cancel(*, order, actor, reason="") -> Order:
    return transition(order=order, to_status=OrderStatus.CANCELLED, actor=actor, note=reason)
