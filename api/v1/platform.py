"""Platform (super admin) surface."""

from django.urls import path

from stores.views_platform import (
    PlatformStoreApproveView,
    PlatformStoreDetailView,
    PlatformStoreListCreateView,
    PlatformStoreSuspendView,
    PlatformUserDetailView,
    PlatformUserListView,
)

app_name = "platform"

urlpatterns = [
    path("stores/", PlatformStoreListCreateView.as_view(), name="store-list"),
    path("stores/<uuid:pk>/", PlatformStoreDetailView.as_view(), name="store-detail"),
    path(
        "stores/<uuid:pk>/approve/",
        PlatformStoreApproveView.as_view(),
        name="store-approve",
    ),
    path(
        "stores/<uuid:pk>/suspend/",
        PlatformStoreSuspendView.as_view(),
        name="store-suspend",
    ),
    path("users/", PlatformUserListView.as_view(), name="user-list"),
    path("users/<uuid:pk>/", PlatformUserDetailView.as_view(), name="user-detail"),
]
