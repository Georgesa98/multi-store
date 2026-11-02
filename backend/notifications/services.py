"""Who gets told what, and when.

Every function here is called from inside the transaction that produced the
event, so the row and the fact it describes commit together. Push is deferred
to `transaction.on_commit` and never delays the response.
"""

from django.db import transaction

from core.enums import NotificationType, OrderStatus
from notifications import push
from notifications.models import Notification

ORDER_UPDATE = NotificationType.ORDER_UPDATE
ASSIGNMENT = NotificationType.ASSIGNMENT
PAYMENT = NotificationType.PAYMENT


def notify(user, *, type, title, body="", data=None) -> Notification:
    notification = Notification.objects.create(
        user=user,
        type=type,
        title=title,
        body=body,
        data=data or {},
    )
    transaction.on_commit(lambda: push.send(notification))
    return notification


def notify_many(users, *, type, title, body="", data=None) -> list[Notification]:
    seen = set()
    created = []
    for user in users:
        if user is None or user.id in seen:
            continue
        seen.add(user.id)
        created.append(notify(user, type=type, title=title, body=body, data=data))
    return created


# ---------------------------------------------------------------------------
# Recipients
# ---------------------------------------------------------------------------


def store_recipients(store):
    """Active team members; the owner always has a membership."""
    return [m.user for m in store.memberships.filter(is_active=True).select_related("user")]


def company_recipients(company):
    return [m.user for m in company.memberships.filter(is_active=True).select_related("user")]


def _order_data(order, status="") -> dict:
    return {
        "order_id": str(order.id),
        "order_number": order.number,
        "status": status,
    }


# ---------------------------------------------------------------------------
# Order lifecycle
# ---------------------------------------------------------------------------


def order_placed(order) -> None:
    """Checkout: the customer gets a receipt, the store a new-order ping."""
    notify(
        order.customer,
        type=ORDER_UPDATE,
        title="Order placed",
        body=f"Order {order.number} at {order.store.name} was received.",
        data=_order_data(order, OrderStatus.PENDING),
    )
    notify_many(
        store_recipients(order.store),
        type=ORDER_UPDATE,
        title="New order",
        body=(
            f"{order.customer.full_name} placed {order.number} for {order.total} {order.currency}."
        ),
        data=_order_data(order, OrderStatus.PENDING),
    )


CUSTOMER_MESSAGES = {
    OrderStatus.CONFIRMED: (ORDER_UPDATE, "Order confirmed", "is confirmed"),
    OrderStatus.PREPARING: (ORDER_UPDATE, "Order being prepared", "is being prepared"),
    OrderStatus.READY: (ORDER_UPDATE, "Order ready", "is ready for pickup"),
    OrderStatus.ASSIGNED: (ORDER_UPDATE, "Courier assigned", "is assigned to a courier"),
    OrderStatus.OUT_FOR_DELIVERY: (ORDER_UPDATE, "Out for delivery", "is on the way"),
    OrderStatus.DELIVERED: (PAYMENT, "Order delivered", "was delivered and paid"),
    OrderStatus.CANCELLED: (ORDER_UPDATE, "Order cancelled", "was cancelled"),
    OrderStatus.REFUNDED: (PAYMENT, "Order refunded", "was refunded"),
}

STORE_MESSAGES = {
    OrderStatus.CANCELLED: ("Order cancelled", "was cancelled"),
    OrderStatus.REFUNDED: ("Order refunded", "was refunded"),
}


def order_status_changed(order, from_status, to_status) -> None:
    """One customer ping per real step.

    A failed attempt or a release moves the order back to `ready`; that is not
    news for the customer, so only the genuine `preparing → ready` speaks.
    """
    if to_status == OrderStatus.READY and from_status in (
        OrderStatus.ASSIGNED,
        OrderStatus.OUT_FOR_DELIVERY,
    ):
        return

    message = CUSTOMER_MESSAGES.get(to_status)
    if message is not None:
        type, title, phrase = message
        notify(
            order.customer,
            type=type,
            title=title,
            body=f"Order {order.number} {phrase}.",
            data=_order_data(order, to_status),
        )

    store_message = STORE_MESSAGES.get(to_status)
    if store_message is not None:
        title, phrase = store_message
        notify_many(
            store_recipients(order.store),
            type=ORDER_UPDATE,
            title=title,
            body=f"Order {order.number} {phrase}.",
            data=_order_data(order, to_status),
        )


# ---------------------------------------------------------------------------
# Delivery lifecycle
# ---------------------------------------------------------------------------


def job_requested(delivery) -> None:
    """A ready order lands in the company's pool."""
    order = delivery.order
    notify_many(
        company_recipients(delivery.company),
        type=ASSIGNMENT,
        title="New delivery job",
        body=f"Order {order.number} is ready for pickup.",
        data=_order_data(order, order.status),
    )


def courier_assigned(delivery, courier) -> None:
    order = delivery.order
    notify(
        courier,
        type=ASSIGNMENT,
        title="Delivery assigned",
        body=f"Order {order.number} at {order.store.name} is yours.",
        data=_order_data(order, order.status),
    )


def job_returned(delivery, reason) -> None:
    """A courier failed the job: the company must dispatch it again."""
    order = delivery.order
    notify_many(
        company_recipients(delivery.company),
        type=ASSIGNMENT,
        title="Delivery failed",
        body=f"Order {order.number} came back: {reason}",
        data=_order_data(order, order.status),
    )
