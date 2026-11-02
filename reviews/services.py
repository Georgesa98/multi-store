"""Review rules: one per delivered item, counters recomputed, replies stamped."""

from django.db import IntegrityError, transaction
from django.db.models import Avg, Count
from django.utils import timezone

from catalog.models import Product
from core.enums import OrderStatus
from core.exceptions import BusinessRuleViolation, Conflict
from core.money import money
from reviews.models import Review


def refresh_product_rating(product_id) -> None:
    """`avg_rating` / `rating_count` are the only denormalised counters here."""
    stats = Review.objects.filter(product_id=product_id).aggregate(
        avg=Avg("rating"), count=Count("id")
    )
    Product.objects.filter(pk=product_id).update(
        avg_rating=money(stats["avg"] or 0),
        rating_count=stats["count"] or 0,
    )


@transaction.atomic
def post_review(*, order_item, customer, rating: int, comment: str = "") -> Review:
    order = order_item.order
    if order.customer_id != customer.id:
        raise BusinessRuleViolation({"detail": "That order item is not yours."})
    if order.status != OrderStatus.DELIVERED:
        raise BusinessRuleViolation({"detail": "Only a delivered order can be reviewed."})
    if Review.objects.filter(order_item=order_item).exists():
        raise Conflict({"detail": "This item has already been reviewed."})

    try:
        with transaction.atomic():
            review = Review.objects.create(
                order_item=order_item,
                customer=customer,
                store_id=order.store_id,
                product_id=order_item.product_id,
                rating=rating,
                comment=comment,
            )
    except IntegrityError as exc:  # two taps racing on the one-to-one
        raise Conflict({"detail": "This item has already been reviewed."}) from exc

    if review.product_id:
        refresh_product_rating(review.product_id)
    return review


@transaction.atomic
def reply(*, review: Review, reply: str) -> Review:
    """The store's public answer; the customer's review itself never changes."""
    review.store_reply = reply
    review.replied_at = timezone.now()
    review.save(update_fields=["store_reply", "replied_at", "updated_at"])
    return review
