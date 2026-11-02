"""How a user maps to a store or a delivery company.

There is deliberately no `User.store` field. A store admin's store comes from
their active `StoreMembership`; a delivery company's staff from their active
`CompanyMembership`. Couriers belong to a delivery company, never to a store,
so they are not store-scoped at all.

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

    return None


def resolve_company_membership(user):
    """The user's single active delivery-company membership, if any."""
    if not getattr(user, "is_authenticated", False):
        return None
    if not getattr(user, "is_active", False):
        return None

    cached = getattr(user, "_active_company_membership", None)
    if cached is not None:
        return cached

    memberships = getattr(user, "company_memberships", None)
    if memberships is None:
        return None

    membership = (
        memberships.filter(is_active=True).select_related("company").order_by("created_at").first()
    )
    user._active_company_membership = membership
    return membership


def resolve_company_id(user):
    if not getattr(user, "is_authenticated", False):
        return None
    if not getattr(user, "is_active", False):
        return None

    company_id = getattr(user, "active_company_id", None)
    if company_id:
        return company_id

    membership = resolve_company_membership(user)
    if membership is not None:
        return membership.company_id

    profile = getattr(user, "courier_profile", None)
    if profile is not None:
        return profile.company_id

    return None
