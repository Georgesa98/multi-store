"""A store's public review wall."""

from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.permissions import AllowAny

from core.enums import StoreStatus
from reviews.models import Review
from reviews.serializers import ReviewSerializer
from stores.models import Store


@extend_schema(tags=["public"])
class PublicStoreReviewListView(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = ReviewSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Review.objects.none()
        store = generics.get_object_or_404(
            Store, slug=self.kwargs["slug"], status=StoreStatus.ACTIVE
        )
        return Review.objects.filter(store=store).select_related("customer", "product")
