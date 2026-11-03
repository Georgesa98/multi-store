"""Basic-auth gate for the API documentation surfaces.

The OpenAPI contract names every endpoint, including `/api/v1/platform/`, so it
is not something to publish by accident: losing the docs is annoying, leaking
the map of a multi-tenant API is worse. The gate is one shared credential from
the environment, checked with a constant-time comparison, and it fails closed —
a production deploy that forgets `DOCS_AUTH_USER`/`DOCS_AUTH_PASSWORD` serves
404 for the docs rather than the schema.
"""

from __future__ import annotations

import base64
import binascii
import secrets

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
