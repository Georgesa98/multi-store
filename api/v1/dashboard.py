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
from stores.views_dashboard import (
    CourierDetailView,
    CourierInviteView,
    CourierListView,
    DeliveryZoneDetailView,
    DeliveryZoneListCreateView,
    OpeningHoursView,
    StoreDetailView,
)

app_name = "dashboard"

urlpatterns = [
    path("store/", StoreDetailView.as_view(), name="store"),
    path("opening-hours/", OpeningHoursView.as_view(), name="opening-hours"),
    path("zones/", DeliveryZoneListCreateView.as_view(), name="zone-list"),
    path("zones/<uuid:pk>/", DeliveryZoneDetailView.as_view(), name="zone-detail"),
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
    path("couriers/", CourierListView.as_view(), name="courier-list"),
    path("couriers/invite/", CourierInviteView.as_view(), name="courier-invite"),
    path("couriers/<uuid:pk>/", CourierDetailView.as_view(), name="courier-detail"),
]
