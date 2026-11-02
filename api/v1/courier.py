"""Courier surface."""

from django.urls import path

from delivery.views_courier import (
    CourierAcceptView,
    CourierAvailabilityView,
    CourierDeclineView,
    CourierDeliverView,
    CourierDeliveryDetailView,
    CourierDeliveryListView,
    CourierEarningsView,
    CourierFailView,
    CourierLocationView,
    CourierMeView,
    CourierOfferListView,
    CourierPickupView,
)

app_name = "courier"

urlpatterns = [
    path("me/", CourierMeView.as_view(), name="me"),
    path("availability/", CourierAvailabilityView.as_view(), name="availability"),
    path("offers/", CourierOfferListView.as_view(), name="offer-list"),
    path("deliveries/", CourierDeliveryListView.as_view(), name="delivery-list"),
    path(
        "deliveries/<uuid:pk>/",
        CourierDeliveryDetailView.as_view(),
        name="delivery-detail",
    ),
    path(
        "deliveries/<uuid:pk>/accept/",
        CourierAcceptView.as_view(),
        name="delivery-accept",
    ),
    path(
        "deliveries/<uuid:pk>/decline/",
        CourierDeclineView.as_view(),
        name="delivery-decline",
    ),
    path(
        "deliveries/<uuid:pk>/pickup/",
        CourierPickupView.as_view(),
        name="delivery-pickup",
    ),
    path(
        "deliveries/<uuid:pk>/location/",
        CourierLocationView.as_view(),
        name="delivery-location",
    ),
    path(
        "deliveries/<uuid:pk>/deliver/",
        CourierDeliverView.as_view(),
        name="delivery-deliver",
    ),
    path(
        "deliveries/<uuid:pk>/fail/",
        CourierFailView.as_view(),
        name="delivery-fail",
    ),
    path("earnings/", CourierEarningsView.as_view(), name="earnings"),
]
