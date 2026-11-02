"""Version 1 URL confs, one module per client surface."""

from django.urls import include, path

urlpatterns = [
    path("auth/", include("api.v1.auth")),
    path("dashboard/", include("api.v1.dashboard")),
    path("platform/", include("api.v1.platform")),
    path("", include("api.v1.addresses")),
    path("", include("api.v1.cart")),
    path("", include("api.v1.orders")),
    path("", include("api.v1.public")),
]
