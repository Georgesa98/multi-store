"""The customer writes one review per delivered order item."""

from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import IsCustomer
from orders.models import OrderItem
from reviews import services
from reviews.serializers import ReviewCreateSerializer, ReviewSerializer


@extend_schema(tags=["reviews"])
class OrderItemReviewView(APIView):
    permission_classes = [IsCustomer]

    @extend_schema(request=ReviewCreateSerializer, responses={201: ReviewSerializer})
    def post(self, request, pk):
        item = generics.get_object_or_404(
            OrderItem.objects.select_related("order"),
            pk=pk,
            order__customer=request.user,
        )
        serializer = ReviewCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        review = services.post_review(
            order_item=item,
            customer=request.user,
            **serializer.validated_data,
        )
        return Response(ReviewSerializer(review).data, status=status.HTTP_201_CREATED)
