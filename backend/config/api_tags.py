"""The reference sidebar's tag groups, one per product surface.

Scalar (the `/api/docs/` viewer) renders the Redoc `x-tagGroups` extension as a
collapsible group per surface, with the tags inside it as a second level. A
crowded tag such as the old `dashboard` (47 operations) therefore reads as seven
small groups of four to fifteen endpoints instead.

The extension has one sharp edge: once `x-tagGroups` is present, Scalar builds
the sidebar only from the tags a group names, so a tag left out of every group
disappears from the page. `tests/test_docs.py` asserts that the declared tags,
the tags operations use and the tags grouped here are the same set, each named
by exactly one group.
"""

TAG_GROUPS = [
    {
        "name": "Authentication",
        "tags": ["Account", "Password", "Device tokens"],
    },
    {
        "name": "Storefront",
        "tags": ["Browse", "Addresses", "Cart", "Orders", "Reviews", "Notifications"],
    },
    {
        "name": "Store dashboard",
        "tags": [
            "Store profile",
            "Catalog",
            "Dashboard orders",
            "Coupons",
            "Delivery partners",
            "Store reviews",
            "Insights",
        ],
    },
    {
        "name": "Delivery company",
        "tags": [
            "Company profile",
            "Team",
            "Couriers",
            "Zones",
            "Dispatch",
            "Company earnings",
        ],
    },
    {
        "name": "Courier",
        "tags": ["Courier profile", "Offers", "My deliveries", "My earnings"],
    },
    {
        "name": "Platform",
        "tags": [
            "Platform stores",
            "Platform companies",
            "Users",
            "Orders and deliveries",
            "Platform coupons",
            "Platform insights",
            "Payouts",
        ],
    },
]


def apply_tag_groups(result=None, **kwargs):
    """drf-spectacular postprocessing hook: publish the sidebar's tag groups."""
    if result is not None:
        result["x-tagGroups"] = TAG_GROUPS
    return result
