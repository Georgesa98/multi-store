"""The customer-facing notification surface, open to every signed-in role."""

from django.urls import path

from notifications.views import (
    NotificationListView,
    NotificationReadAllView,
    NotificationReadView,
)

app_name = "notifications"

urlpatterns = [
    path("notifications/", NotificationListView.as_view(), name="notification-list"),
    path(
        "notifications/<uuid:pk>/read/",
        NotificationReadView.as_view(),
        name="notification-read",
    ),
    path(
        "notifications/read-all/",
        NotificationReadAllView.as_view(),
        name="notification-read-all",
    ),
]
