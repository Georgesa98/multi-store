"""The error envelope, and the responses drf-spectacular cannot infer.

Two gaps in the generated schema are closed here:

* drf-spectacular 0.28 has no notion of throttling. `DEFAULT_THROTTLE_CLASSES`
  applies to every `/api/v1/` operation, but none of them documents a `429`, so
  a client that never saw one in the reference page treats it as a crash.
* The API answers `{"detail": ..., "code": ...}` for object-level errors
  (`core.handlers`), and `code` is the machine-readable contract. Documenting
  the component once gives clients the enum without repeating it 157 times.

The hook runs over the finished schema, so the component it inserts is the same
object every `429` points at.
"""

from copy import deepcopy

# Every `code` the handler can emit. Add to this list when a new exception
# class is introduced; the reference page reads it as an enum.
ERROR_CODES = [
    "invalid",
    "parse_error",
    "authentication_failed",
    "not_authenticated",
    "permission_denied",
    "not_found",
    "method_not_allowed",
    "not_acceptable",
    "unsupported_media_type",
    "conflict",
    "invalid_transition",
    "business_rule",
    "throttled",
    "account_locked",
]

API_ERROR_SCHEMA = {
    "type": "object",
    "description": (
        "An object-level error. `code` is stable and safe to branch on. "
        "Field-validation errors use DRF's shape instead, "
        '`{"field": ["..."]}`, with no top-level `code`.'
    ),
    "properties": {
        "detail": {"type": "string"},
        "code": {"type": "string", "enum": ERROR_CODES},
        "request_id": {
            "type": "string",
            "description": (
                "The correlation id, the same value as the `X-Request-ID` "
                "response header. Quote it when reporting a failure."
            ),
        },
    },
    "required": ["detail", "code"],
}

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
    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiError"}}},
}


def apply_error_responses(result, generator, request, public):
    """Publish the error component and the `429` every operation can answer."""
    result.setdefault("components", {}).setdefault("schemas", {})["ApiError"] = deepcopy(
        API_ERROR_SCHEMA
    )

    for operations in result.get("paths", {}).values():
        for operation in operations.values():
            if isinstance(operation, dict) and "responses" in operation:
                operation["responses"].setdefault("429", deepcopy(THROTTLED_RESPONSE))
    return result
