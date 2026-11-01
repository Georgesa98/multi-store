"""How a user maps to a store.

There is deliberately no `User.store` field. A store admin's store comes from
their active `StoreMembership`; a courier's from `CourierProfile.store`. The
brief's `for_user()` sketch assumed `user.store_id`, which does not exist, so
resolution is centralised here and every store-scoped query uses it.

Resolution happens in the view layer (permission classes), not in middleware:
DRF authenticates the JWT per view, so a Django middleware would only ever see
an AnonymousUser.
"""


def resolve_membership(user):
    """The user's single active store membership, if any."""
    if not getattr(user, "is_authenticated", False):
        return None
    if not getattr(user, "is_active", False):
        return None

    cached = getattr(user, "_active_membership", None)
    if cached is not None:
        return cached

    memberships = getattr(user, "memberships", None)
    if memberships is None:
        return None

    membership = (
        memberships.filter(is_active=True).select_related("store").order_by("created_at").first()
    )
    user._active_membership = membership
    return membership


def resolve_store_id(user):
    if not getattr(user, "is_authenticated", False):
        return None
    if not getattr(user, "is_active", False):
        return None

    # Fast path: callers may annotate/attach the resolved store.
    store_id = getattr(user, "active_store_id", None)
    if store_id:
        return store_id

    membership = resolve_membership(user)
    if membership is not None:
        return membership.store_id

    profile = getattr(user, "courier_profile", None)
    if profile is not None:
        return profile.store_id

    return None
