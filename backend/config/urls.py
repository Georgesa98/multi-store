"""Root URL configuration.

`/admin/` is mounted in DEBUG only — it is a developer convenience, never a
product surface. Platform capabilities live under `/api/v1/platform/`.
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

urlpatterns = [
    path("api/v1/", include("api.v1.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
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
