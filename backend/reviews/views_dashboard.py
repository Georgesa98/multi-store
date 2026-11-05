"""Store dashboard: read reviews, answer them."""

from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import IsDashboardUser, IsDashboardWriter
from reviews import services
from reviews.models import Review
from reviews.serializers import ReviewReplySerializer, ReviewSerializer


@extend_schema(tags=["Store reviews"])
class DashboardReviewListView(generics.ListAPIView):
    permission_classes = [IsDashboardUser]
    serializer_class = ReviewSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Review.objects.none()
        return Review.objects.filter(store=self.request.store).select_related("customer", "product")


@extend_schema(tags=["Store reviews"])
class DashboardReviewReplyView(APIView):
    permission_classes = [IsDashboardWriter]

    @extend_schema(request=ReviewReplySerializer, responses=ReviewSerializer)
    def post(self, request, pk):
        review = generics.get_object_or_404(Review, pk=pk, store=request.store)
        serializer = ReviewReplySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        review = services.reply(review=review, reply=serializer.validated_data["reply"])
        return Response(ReviewSerializer(review).data)
