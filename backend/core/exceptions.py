"""Exception types that map onto the documented HTTP status codes."""

from rest_framework.exceptions import APIException, Throttled


class Conflict(APIException):
    """409 — illegal state transition or a concurrent change."""

    status_code = 409
    default_detail = "This action conflicts with the current state."
    default_code = "conflict"


class BusinessRuleViolation(APIException):
    """422 — well-formed request that breaks a business rule."""

    status_code = 422
    default_detail = "This request breaks a business rule."
    default_code = "business_rule"


class InvalidTransition(Conflict):
    """409 — the requested order state change is not in the transition table."""

    default_detail = "That status change is not allowed."
    default_code = "invalid_transition"


class AccountLocked(Throttled):
    """429 — too many failed sign-ins for this email; wait, then try again.

    A `Throttled` subclass on purpose: DRF sends `Retry-After` for it, which is
    exactly what a client needs, and the `code` stays distinct from the IP
    throttle's `throttled`.
    """

    default_detail = "Too many failed sign-in attempts for this account."
    default_code = "account_locked"
