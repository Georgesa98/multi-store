"""Small views that are not part of the API surface.

`healthz` exists for the container runtime (Docker HEALTHCHECK / Coolify) and
`api_docs` renders the reference page from the schema the process would serve,
so the page cannot describe an API this build does not have.
"""

from django.db import connections
from django.http import JsonResponse
from django.template.response import TemplateResponse
from drf_spectacular.generators import SchemaGenerator


def healthz(request):
    """Liveness plus a database round trip. Never cached, never authenticated."""
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:  # noqa: BLE001 - any failure means "not ready"
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})


def api_docs(request):
    """The Scalar reference page, with the contract embedded.

    The schema is generated here instead of fetched by the browser for two
    reasons: the page is behind the docs credential, and a fetch from a gated
    page depends on the browser replaying that credential, which is not
    something to bet the docs page on.
    """
    schema = SchemaGenerator().get_schema(request=None, public=True)
    response = TemplateResponse(request, "api/docs.html", {"schema": schema})
    response["Cache-Control"] = "no-store"
    return response
