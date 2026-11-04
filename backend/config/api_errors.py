"""Error responses the generator cannot infer from the code.

drf-spectacular 0.28 has no notion of throttling: `DEFAULT_THROTTLE_CLASSES`
applies to every `/api/v1/` operation, but none of them documents a `429`. A
client that never saw one in the reference page treats it as a crash. The hook
below adds it everywhere, with the body shape the exception handler renders and
the `Retry-After` header DRF sends.
"""

from copy import deepcopy

THROTTLED_RESPONSE = {
    "description": (
        "Too many requests for this endpoint. `Retry-After` carries the number "
        "of seconds to wait before retrying."
    ),
    "headers": {
        "Retry-After": {
            "description": "Seconds until the next request is allowed.",
            "schema": {"type": "integer"},
        }
    },
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "properties": {"detail": {"type": "string"}},
                "required": ["detail"],
            }
        }
    },
}


def apply_error_responses(result, generator, request, public):
    """Document the `429` every throttled operation can answer."""
    for operations in result.get("paths", {}).values():
        for operation in operations.values():
            if isinstance(operation, dict) and "responses" in operation:
                operation["responses"].setdefault("429", deepcopy(THROTTLED_RESPONSE))
    return result
