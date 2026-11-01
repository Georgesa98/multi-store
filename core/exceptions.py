"""Exception types that map onto the documented HTTP status codes."""

from rest_framework.exceptions import APIException


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
