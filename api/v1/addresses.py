"""Customer address book."""

from django.urls import path

from accounts.views_addresses import (
    AddressDetailView,
    AddressListCreateView,
    AddressSetDefaultView,
)

app_name = "addresses"

urlpatterns = [
    path("addresses/", AddressListCreateView.as_view(), name="address-list"),
    path("addresses/<uuid:pk>/", AddressDetailView.as_view(), name="address-detail"),
    path(
        "addresses/<uuid:pk>/set-default/",
        AddressSetDefaultView.as_view(),
        name="address-set-default",
    ),
]
