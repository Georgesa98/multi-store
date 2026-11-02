"""Cart surface."""

from django.urls import path

from cart.views import (
    CartClearView,
    CartCouponView,
    CartItemCreateView,
    CartItemDetailView,
    CartListCreateView,
)

app_name = "cart"

urlpatterns = [
    path("carts/", CartListCreateView.as_view(), name="cart-list"),
    path("carts/<uuid:pk>/items/", CartItemCreateView.as_view(), name="cart-items"),
    path(
        "carts/<uuid:pk>/items/<uuid:item_pk>/",
        CartItemDetailView.as_view(),
        name="cart-item-detail",
    ),
    path("carts/<uuid:pk>/coupon/", CartCouponView.as_view(), name="cart-coupon"),
    path("carts/<uuid:pk>/clear/", CartClearView.as_view(), name="cart-clear"),
]
