"""Customer cart surface. Every query is scoped to `request.user`."""

from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from cart import services
from cart.models import Cart, CartItem
from cart.serializers import (
    AddItemSerializer,
    ApplyCouponSerializer,
    CartCreateSerializer,
    CartItemSerializer,
    CartSerializer,
    UpdateItemSerializer,
)
from catalog.models import ProductVariant
from core.enums import StoreStatus
from core.permissions import IsCustomer
from stores.models import Store


def _cart_or_404(request, pk) -> Cart:
    return generics.get_object_or_404(Cart, pk=pk, customer=request.user)


def _prefetch(carts):
    return carts.select_related("store", "coupon").prefetch_related(
        "items__variant__product__images"
    )


@extend_schema(tags=["Cart"])
class CartListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsCustomer]
    serializer_class = CartSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Cart.objects.none()
        return _prefetch(Cart.objects.filter(customer=self.request.user)).order_by("store__name")

    @extend_schema(
        request=CartCreateSerializer,
        responses={200: CartSerializer, 201: CartSerializer},
        description="Get-or-create this customer's cart for one store.",
    )
    def post(self, request, *args, **kwargs):
        serializer = CartCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        store = generics.get_object_or_404(
            Store, pk=serializer.validated_data["store"], status=StoreStatus.ACTIVE
        )
        existed = Cart.objects.filter(customer=request.user, store=store).exists()
        cart = services.get_or_create_cart(customer=request.user, store=store)
        cart = _prefetch(Cart.objects.filter(pk=cart.pk)).get()
        return Response(
            CartSerializer(cart, context={"request": request}).data,
            status=status.HTTP_200_OK if existed else status.HTTP_201_CREATED,
        )


@extend_schema(tags=["Cart"])
class CartItemCreateView(APIView):
    permission_classes = [IsCustomer]

    @extend_schema(request=AddItemSerializer, responses={201: CartItemSerializer})
    def post(self, request, pk):
        cart = _cart_or_404(request, pk)
        serializer = AddItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        variant = generics.get_object_or_404(
            ProductVariant.objects.select_related("product"),
            pk=serializer.validated_data["variant"],
        )
        item = services.add_item(
            cart=cart,
            variant=variant,
            quantity=serializer.validated_data["quantity"],
        )
        item = (
            CartItem.objects.select_related("variant__product")
            .prefetch_related("variant__product__images")
            .get(pk=item.pk)
        )
        return Response(
            CartItemSerializer(item, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema(tags=["Cart"])
class CartItemDetailView(APIView):
    permission_classes = [IsCustomer]

    def get_item(self, request, pk, item_id) -> CartItem:
        cart = _cart_or_404(request, pk)
        return generics.get_object_or_404(
            CartItem.objects.select_related("variant__product"), pk=item_id, cart=cart
        )

    @extend_schema(
        request=UpdateItemSerializer,
        responses={200: CartItemSerializer, 204: None},
        description="Setting the quantity to zero removes the item.",
    )
    def patch(self, request, pk, item_id):
        item = self.get_item(request, pk, item_id)
        serializer = UpdateItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = services.update_item(item=item, quantity=serializer.validated_data["quantity"])
        if item is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        item = (
            CartItem.objects.select_related("variant__product")
            .prefetch_related("variant__product__images")
            .get(pk=item.pk)
        )
        return Response(CartItemSerializer(item, context={"request": request}).data)

    @extend_schema(responses={204: None})
    def delete(self, request, pk, item_id):
        services.remove_item(self.get_item(request, pk, item_id))
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["Cart"])
class CartCouponView(APIView):
    permission_classes = [IsCustomer]

    @extend_schema(request=ApplyCouponSerializer, responses=CartSerializer)
    def post(self, request, pk):
        cart = _cart_or_404(request, pk)
        serializer = ApplyCouponSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.apply_coupon(cart=cart, code=serializer.validated_data["code"])
        cart = _prefetch(Cart.objects.filter(pk=cart.pk)).get()
        return Response(CartSerializer(cart, context={"request": request}).data)

    @extend_schema(responses={204: None})
    def delete(self, request, pk):
        services.remove_coupon(_cart_or_404(request, pk))
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["Cart"])
class CartClearView(APIView):
    permission_classes = [IsCustomer]

    @extend_schema(request=None, responses={204: None})
    def post(self, request, pk):
        services.clear_cart(_cart_or_404(request, pk))
        return Response(status=status.HTTP_204_NO_CONTENT)
