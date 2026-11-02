"""Platform (super admin) surface."""

from django.urls import path

from analytics.views_platform import (
    PlatformLedgerView,
    PlatformOverviewView,
    PlatformPayoutListView,
    PlatformPayoutMarkPaidView,
    PlatformPayoutSettleView,
    PlatformRevenueView,
)
from delivery.views_platform import (
    PlatformCompanyApproveView,
    PlatformCompanyDetailView,
    PlatformCompanyListCreateView,
    PlatformCompanySuspendView,
    PlatformDeliveryListView,
)
from orders.views_platform import PlatformCouponListCreateView, PlatformOrderListView
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
    path("companies/", PlatformCompanyListCreateView.as_view(), name="company-list"),
    path(
        "companies/<uuid:pk>/",
        PlatformCompanyDetailView.as_view(),
        name="company-detail",
    ),
    path(
        "companies/<uuid:pk>/approve/",
        PlatformCompanyApproveView.as_view(),
        name="company-approve",
    ),
    path(
        "companies/<uuid:pk>/suspend/",
        PlatformCompanySuspendView.as_view(),
        name="company-suspend",
    ),
    path("users/", PlatformUserListView.as_view(), name="user-list"),
    path("users/<uuid:pk>/", PlatformUserDetailView.as_view(), name="user-detail"),
    path("orders/", PlatformOrderListView.as_view(), name="order-list"),
    path("deliveries/", PlatformDeliveryListView.as_view(), name="delivery-list"),
    path("coupons/", PlatformCouponListCreateView.as_view(), name="coupon-list"),
    path("insights/overview/", PlatformOverviewView.as_view(), name="insight-overview"),
    path("insights/revenue/", PlatformRevenueView.as_view(), name="insight-revenue"),
    path("ledger/", PlatformLedgerView.as_view(), name="ledger"),
    path("payouts/", PlatformPayoutListView.as_view(), name="payout-list"),
    path(
        "payouts/<uuid:pk>/settle/",
        PlatformPayoutSettleView.as_view(),
        name="payout-settle",
    ),
    path(
        "payouts/<uuid:pk>/mark-paid/",
        PlatformPayoutMarkPaidView.as_view(),
        name="payout-mark-paid",
    ),
]
