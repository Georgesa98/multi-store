from django.urls import path

from accounts import views

app_name = "auth"

urlpatterns = [
    path("register/", views.RegisterView.as_view(), name="register"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("refresh/", views.RefreshView.as_view(), name="refresh"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("me/", views.MeView.as_view(), name="me"),
    path("password/change/", views.PasswordChangeView.as_view(), name="password-change"),
    path("password/reset/", views.PasswordResetView.as_view(), name="password-reset"),
    path(
        "password/reset/confirm/",
        views.PasswordResetConfirmView.as_view(),
        name="password-reset-confirm",
    ),
    path(
        "device-tokens/",
        views.DeviceTokenListCreateView.as_view(),
        name="device-token-list",
    ),
    path(
        "device-tokens/<uuid:pk>/",
        views.DeviceTokenDetailView.as_view(),
        name="device-token-detail",
    ),
]
