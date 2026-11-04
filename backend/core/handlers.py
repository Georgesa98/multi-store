"""One error shape for the whole API.

Every object-level error answers `{"detail": ..., "code": ...}`. The prose is
for humans; `code` is the contract, so a client can branch on `conflict` or
`invalid_transition` without matching an English sentence that may be reworded.
The code comes from DRF's `ErrorDetail`, which means the exception classes in
`core.exceptions` decide it (`Conflict` → `conflict`, `InvalidTransition` →
`invalid_transition`, `BusinessRuleViolation` → `business_rule`) and DRF's own
exceptions keep theirs (`not_found`, `permission_denied`, `throttled`, …).

Field validation is deliberately untouched: `{"field": ["..."]}` is the shape
DRF clients already parse, and wrapping it would be a breaking change for no
gain. A `ValidationError` never gets a top-level `code`.
"""

from rest_framework.exceptions import ValidationError
from rest_framework.views import exception_handler as drf_exception_handler


def api_exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    if isinstance(exc, ValidationError):
        return response

    data = response.data
    if isinstance(data, dict) and "detail" in data:
        detail = data["detail"]
        code = getattr(detail, "code", None) or getattr(exc, "default_code", None)
        response.data = {"detail": detail, "code": code or "error"}
    return response
