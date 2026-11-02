"""Store dashboard surface."""

from django.urls import path

from catalog.views_dashboard import (
    CategoryDetailView,
    CategoryListCreateView,
    InventoryMovementListView,
    ProductDetailView,
    ProductImageUploadView,
    ProductListCreateView,
    ProductVariantCreateView,
    VariantDetailView,
    VariantStockView,
)
from delivery.views_dashboard import (
    AvailableCompanyListView,
    PartnerDetailView,
    PartnerListView,
    StoreDeliveryDetailView,
    StoreDeliveryListView,
    StoreDeliveryRequestView,
)
from orders.views_dashboard import (
    DashboardOrderCancelView,
    DashboardOrderConfirmView,
    DashboardOrderDetailView,
    DashboardOrderListView,
    DashboardOrderPreparingView,
    DashboardOrderReadyView,
)
from stores.views_dashboard import OpeningHoursView, StoreDetailView

app_name = "dashboard"

urlpatterns = [
    path("store/", StoreDetailView.as_view(), name="store"),
    path("opening-hours/", OpeningHoursView.as_view(), name="opening-hours"),
    path("categories/", CategoryListCreateView.as_view(), name="category-list"),
    path("categories/<uuid:pk>/", CategoryDetailView.as_view(), name="category-detail"),
    path("products/", ProductListCreateView.as_view(), name="product-list"),
    path("products/<uuid:pk>/", ProductDetailView.as_view(), name="product-detail"),
    path(
        "products/<uuid:pk>/images/",
        ProductImageUploadView.as_view(),
        name="product-images",
    ),
    path(
        "products/<uuid:pk>/variants/",
        ProductVariantCreateView.as_view(),
        name="product-variants",
    ),
    path("variants/<uuid:pk>/", VariantDetailView.as_view(), name="variant-detail"),
    path("variants/<uuid:pk>/stock/", VariantStockView.as_view(), name="variant-stock"),
    path(
        "inventory-movements/",
        InventoryMovementListView.as_view(),
        name="inventory-movements",
    ),
    # Delivery partners and their jobs.
    path("companies/", AvailableCompanyListView.as_view(), name="company-list"),
    path("partners/", PartnerListView.as_view(), name="partner-list"),
    path("partners/<uuid:pk>/", PartnerDetailView.as_view(), name="partner-detail"),
    path("deliveries/", StoreDeliveryListView.as_view(), name="delivery-list"),
    path(
        "deliveries/<uuid:pk>/",
        StoreDeliveryDetailView.as_view(),
        name="delivery-detail",
    ),
    path(
        "deliveries/<uuid:pk>/request/",
        StoreDeliveryRequestView.as_view(),
        name="delivery-request",
    ),
    path("orders/", DashboardOrderListView.as_view(), name="order-list"),
    path("orders/<uuid:pk>/", DashboardOrderDetailView.as_view(), name="order-detail"),
    path(
        "orders/<uuid:pk>/confirm/",
        DashboardOrderConfirmView.as_view(),
        name="order-confirm",
    ),
    path(
        "orders/<uuid:pk>/preparing/",
        DashboardOrderPreparingView.as_view(),
        name="order-preparing",
    ),
    path(
        "orders/<uuid:pk>/ready/",
        DashboardOrderReadyView.as_view(),
        name="order-ready",
    ),
    path(
        "orders/<uuid:pk>/cancel/",
        DashboardOrderCancelView.as_view(),
        name="order-cancel",
    ),
]
