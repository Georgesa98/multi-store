"""Root URL configuration.

`/admin/` is mounted in DEBUG only — it is a developer convenience, never a
product surface. Platform capabilities live under `/api/v1/platform/`.

The docs surfaces (`/api/schema/`, `/api/docs/`, `/api/redoc/`) are gated by
`core.middleware.DocsGateMiddleware`; see that module for the rules.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from config.views import api_docs, healthz

urlpatterns = [
    path("api/v1/", include("api.v1.urls")),
    path("healthz/", healthz, name="healthz"),
    # The contract itself: what clients generate their types from.
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    # The reference page (Scalar), backed by the schema above.
    path("api/docs/", api_docs, name="docs"),
    # Swagger UI stays as the do-everything fallback.
    path(
        "api/docs/swagger/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path(
        "api/redoc/",
        SpectacularRedocView.as_view(url_name="schema"),
        name="redoc",
    ),
]

if settings.DEBUG:
    urlpatterns += [
        path("admin/", admin.site.urls),
        *static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT),
    ]
