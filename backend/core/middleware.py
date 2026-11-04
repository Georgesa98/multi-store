"""Cross-cutting middleware: the docs gate and the request id.

The docs gate keeps the OpenAPI contract private; the request id makes a
support ticket traceable to the log lines that produced the error.
"""

from __future__ import annotations

import base64
import binascii
import logging
import re
import secrets
import uuid
from contextvars import ContextVar

from django.conf import settings
from django.http import Http404, HttpResponse

GATED_PREFIXES = ("/api/schema", "/api/docs", "/api/redoc")


def _basic_credentials(request):
    """Return `(username, password)` from a Basic header, or None."""
    header = request.headers.get("Authorization", "")
    scheme, _, payload = header.partition(" ")
    if scheme.lower() != "basic" or not payload:
        return None
    try:
        decoded = base64.b64decode(payload, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
    username, separator, password = decoded.partition(":")
    if not separator:
        return None
    return username, password


def _matches(supplied, expected):
    return secrets.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))


class DocsGateMiddleware:
    """Require the shared docs credential outside DEBUG.

    Development is left open so `runserver` stays frictionless; a browser that
    has authenticated to `/api/docs/` reuses the same credential for the schema
    and for Swagger, which fetch them from the same origin.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith(GATED_PREFIXES):
            denied = self._denial(request)
            if denied is not None:
                return denied
        return self.get_response(request)

    @staticmethod
    def _denial(request):
        username = settings.DOCS_AUTH_USER
        password = settings.DOCS_AUTH_PASSWORD

        if not username or not password:
            # Fail closed: no credential configured means the routes do not exist.
            if settings.DEBUG:
                return None
            raise Http404

        credentials = _basic_credentials(request)
        if credentials is None or not (
            _matches(credentials[0], username) and _matches(credentials[1], password)
        ):
            return HttpResponse(
                status=401,
                headers={"WWW-Authenticate": 'Basic realm="API docs", charset="UTF-8"'},
            )
        return None


# ---------------------------------------------------------------------------
# Request id
# ---------------------------------------------------------------------------

# Callers may supply their own id (a gateway, an APM agent), but it is echoed
# into a response header, so anything outside this set is replaced rather than
# trusted: a header value must not be able to smuggle a newline.
REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,128}")

request_id_var: ContextVar[str] = ContextVar("request_id", default="")


class RequestIDLogFilter(logging.Filter):
    """Put the current request's id on every record, `-` outside a request."""

    def filter(self, record):
        record.request_id = request_id_var.get() or "-"
        return True


class RequestIDMiddleware:
    """Echo `X-Request-ID` back (or mint one) and make it available to logs.

    The id is also written into object-level error bodies by `core.handlers`,
    so a user can quote one identifier that appears in the response, in the
    access log and in the traceback.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming = request.headers.get("X-Request-ID", "")
        request_id = incoming if REQUEST_ID_PATTERN.fullmatch(incoming) else uuid.uuid4().hex
        request.request_id = request_id

        token = request_id_var.set(request_id)
        try:
            response = self.get_response(request)
            response["X-Request-ID"] = request_id
            return response
        finally:
            request_id_var.reset(token)
