"""How a user maps to a store.

There is deliberately no `User.store` field. A store admin's store comes from
their active `StoreMembership`; a courier's from `CourierProfile.store`. The
brief's `for_user()` sketch assumed `user.store_id`, which does not exist, so
resolution is centralised here and every store-scoped query uses it.
"""


def resolve_store_id(user):
    if not getattr(user, "is_authenticated", False):
        return None
    if not getattr(user, "is_active", False):
        return None

    # Fast path: callers may annotate/attach the resolved store.
    store_id = getattr(user, "active_store_id", None)
    if store_id:
        return store_id

    membership = _active_membership(user)
    if membership is not None:
        return membership.store_id

    profile = getattr(user, "courier_profile", None)
    if profile is not None:
        return profile.store_id

    return None


def _active_membership(user):
    memberships = getattr(user, "memberships", None)
    if memberships is None:
        return None
    return memberships.filter(is_active=True).select_related(None).order_by("created_at").first()
