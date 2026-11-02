"""Delivery-company surface."""

from django.urls import path

from delivery.views_company import (
    CompanyDeliveryTicketView,
    CompanyDetailView,
    CompanyEarningsView,
    CompanyMemberDetailView,
    CompanyMemberInviteView,
    CompanyMemberListView,
    CourierDetailView,
    CourierListView,
    DeliveryAssignView,
    DeliveryDetailView,
    DeliveryFailView,
    DeliveryListView,
    DeliveryReleaseView,
    ZoneDetailView,
    ZoneListCreateView,
)

app_name = "company"

urlpatterns = [
    path("company/", CompanyDetailView.as_view(), name="company-detail"),
    path("members/", CompanyMemberListView.as_view(), name="member-list"),
    path(
        "members/invite/",
        CompanyMemberInviteView.as_view(),
        name="member-invite",
    ),
    path(
        "members/<uuid:pk>/",
        CompanyMemberDetailView.as_view(),
        name="member-detail",
    ),
    path("couriers/", CourierListView.as_view(), name="courier-list"),
    path("couriers/<uuid:pk>/", CourierDetailView.as_view(), name="courier-detail"),
    path("zones/", ZoneListCreateView.as_view(), name="zone-list"),
    path("zones/<uuid:pk>/", ZoneDetailView.as_view(), name="zone-detail"),
    path("deliveries/", DeliveryListView.as_view(), name="delivery-list"),
    path("deliveries/<uuid:pk>/", DeliveryDetailView.as_view(), name="delivery-detail"),
    path(
        "deliveries/<uuid:pk>/assign/",
        DeliveryAssignView.as_view(),
        name="delivery-assign",
    ),
    path(
        "deliveries/<uuid:pk>/release/",
        DeliveryReleaseView.as_view(),
        name="delivery-release",
    ),
    path(
        "deliveries/<uuid:pk>/fail/",
        DeliveryFailView.as_view(),
        name="delivery-fail",
    ),
    path("earnings/", CompanyEarningsView.as_view(), name="earnings"),
    path(
        "deliveries/<uuid:pk>/ws-ticket/",
        CompanyDeliveryTicketView.as_view(),
        name="delivery-ws-ticket",
    ),
]
