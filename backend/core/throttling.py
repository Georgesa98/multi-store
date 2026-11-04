"""Rate limiting.

DRF's `ScopedRateThrottle` only reads a view's `throttle_scope`; the actual
counter is created per class. A view that wants its own budget therefore has to
declare the whole `throttle_classes` list, or it silently loses the global
anon/user buckets. `ScopedThrottleMixin` puts the three back together so a view
only names its scope:

    class LoginView(ScopedThrottleMixin, APIView):
        throttle_scope = "auth"

Rates live in `REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]` (and are environment
overrides), so tuning them needs no code change. A view with no `throttle_scope`
still gets the global budgets from `DEFAULT_THROTTLE_CLASSES`.
"""

from rest_framework.throttling import AnonRateThrottle, ScopedRateThrottle, UserRateThrottle


class ScopedThrottleMixin:
    """Global anon/user budgets plus the view's named `throttle_scope`."""

    throttle_classes = (AnonRateThrottle, UserRateThrottle, ScopedRateThrottle)
