from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from accounts import services
from accounts.models import DeviceToken
from accounts.serializers import (
    AuthResponseSerializer,
    DeviceTokenSerializer,
    LoginSerializer,
    LogoutSerializer,
    PasswordChangeSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    RegisterSerializer,
    UserSerializer,
)

User = get_user_model()


@extend_schema(tags=["auth"])
class RegisterView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(request=RegisterSerializer, responses={201: AuthResponseSerializer})
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = services.register_customer(**serializer.validated_data)
        payload = {"role": user.role, "user": UserSerializer(user).data}
        payload.update(services.issue_tokens(user))
        return Response(payload, status=status.HTTP_201_CREATED)


@extend_schema(tags=["auth"])
class LoginView(TokenObtainPairView):
    permission_classes = [AllowAny]
    serializer_class = LoginSerializer

    @extend_schema(request=LoginSerializer, responses={200: AuthResponseSerializer})
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


@extend_schema(tags=["auth"])
class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=LogoutSerializer, responses={204: None})
    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            RefreshToken(serializer.validated_data["refresh"]).blacklist()
        except TokenError:
            return Response(
                {"detail": "Token is invalid or expired."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["auth"])
class MeView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user


@extend_schema(tags=["auth"])
class PasswordChangeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=PasswordChangeSerializer, responses={204: None})
    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.change_password(
            user=request.user,
            old_password=serializer.validated_data["old_password"],
            new_password=serializer.validated_data["new_password"],
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["auth"])
class PasswordResetView(APIView):
    """Always answers 204 so the endpoint cannot be used to enumerate accounts."""

    permission_classes = [AllowAny]

    @extend_schema(request=PasswordResetRequestSerializer, responses={204: None})
    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = User.objects.filter(
            email__iexact=serializer.validated_data["email"], is_active=True
        ).first()
        if user is not None:
            uid, token = services.make_password_reset_token(user)
            reset_url = f"{settings.FRONTEND_URL}/reset-password?uid={uid}&token={token}"
            send_mail(
                subject="Reset your password",
                message=f"Use this link to reset your password: {reset_url}",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=True,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["auth"])
class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(request=PasswordResetConfirmSerializer, responses={204: None})
    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = services.resolve_password_reset_token(data["uid"], data["token"])
        if user is None:
            return Response(
                {"detail": "This reset link is invalid or has expired."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        services.change_password(
            user=user,
            old_password=None,
            new_password=data["new_password"],
            skip_old_password=True,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["auth"])
class DeviceTokenListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DeviceTokenSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return DeviceToken.objects.none()
        return DeviceToken.objects.filter(user=self.request.user, is_active=True)

    @extend_schema(responses={201: DeviceTokenSerializer})
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


@extend_schema(tags=["auth"])
class DeviceTokenDetailView(generics.DestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DeviceTokenSerializer
    lookup_field = "pk"

    def get_queryset(self):
        # Cross-user access is a 404, never a 403: no existence leak.
        if getattr(self, "swagger_fake_view", False):
            return DeviceToken.objects.none()
        return DeviceToken.objects.filter(user=self.request.user)
