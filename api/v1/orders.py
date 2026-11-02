"""Customer checkout and order history."""

from django.urls import path

from orders.views import (
    CheckoutGroupDetailView,
    CheckoutGroupListView,
    CheckoutPreviewView,
    CheckoutView,
    OrderCancelView,
    OrderDetailView,
    OrderListView,
    OrderTimelineView,
)

app_name = "orders"

urlpatterns = [
    path("checkout/preview/", CheckoutPreviewView.as_view(), name="checkout-preview"),
    path("checkout/", CheckoutView.as_view(), name="checkout"),
    path(
        "checkout-groups/",
        CheckoutGroupListView.as_view(),
        name="checkout-group-list",
    ),
    path(
        "checkout-groups/<uuid:pk>/",
        CheckoutGroupDetailView.as_view(),
        name="checkout-group-detail",
    ),
    path("orders/", OrderListView.as_view(), name="order-list"),
    path("orders/<uuid:pk>/", OrderDetailView.as_view(), name="order-detail"),
    path("orders/<uuid:pk>/timeline/", OrderTimelineView.as_view(), name="order-timeline"),
    path("orders/<uuid:pk>/cancel/", OrderCancelView.as_view(), name="order-cancel"),
]
