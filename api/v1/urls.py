"""Version 1 URL confs, one module per client surface.

Surfaces are added as their phase lands:
  auth       Phase 0
  public     Phase 2 (customer catalogue/cart/checkout/orders)
  dashboard  Phase 1 (store admin)
  courier    Phase 3
  platform   Phase 1
"""

from django.urls import include, path

urlpatterns = [
    path("auth/", include("api.v1.auth")),
]
