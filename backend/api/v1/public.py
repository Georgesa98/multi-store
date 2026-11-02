"""Customer-facing store and catalogue browsing (no auth required)."""

from django.urls import path

from catalog.views_public import (
    PublicCategoryListView,
    PublicProductDetailView,
    PublicProductListView,
)
from reviews.views_public import PublicStoreReviewListView
from stores.views_public import (
    DeliveryQuoteView,
    PublicStoreDetailView,
    PublicStoreListView,
)

app_name = "public"

urlpatterns = [
    path("stores/", PublicStoreListView.as_view(), name="store-list"),
    path(
        "stores/<slug:store_slug>/products/<slug:slug>/",
        PublicProductDetailView.as_view(),
        name="store-product-detail",
    ),
    path(
        "stores/<slug:slug>/products/",
        PublicProductListView.as_view(),
        name="store-product-list",
    ),
    path(
        "stores/<slug:slug>/categories/",
        PublicCategoryListView.as_view(),
        name="store-category-list",
    ),
    path(
        "stores/<slug:slug>/delivery-quote/",
        DeliveryQuoteView.as_view(),
        name="store-delivery-quote",
    ),
    path(
        "stores/<slug:slug>/reviews/",
        PublicStoreReviewListView.as_view(),
        name="store-review-list",
    ),
    path("stores/<slug:slug>/", PublicStoreDetailView.as_view(), name="store-detail"),
]
