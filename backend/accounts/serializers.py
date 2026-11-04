from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from accounts.models import Address, DeviceToken
from core.enums import Role

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "full_name",
            "phone",
            "role",
            "is_active",
            "date_joined",
            "last_login",
        )
        read_only_fields = ("id", "email", "role", "is_active", "date_joined", "last_login")


class PlatformUserUpdateSerializer(serializers.ModelSerializer):
    """What a platform admin may change on someone else's account.

    `is_active` is read-only on `UserSerializer` so a customer cannot flip their
    own switch; this is the one surface where it is writable.
    """

    class Meta:
        model = User
        fields = ("full_name", "is_active")


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    full_name = serializers.CharField(max_length=150)
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value.lower()

    def validate_password(self, value):
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc
        return value


class LoginSerializer(TokenObtainPairSerializer):
    """Email + password, with the user payload the apps need after login."""

    def validate(self, attrs):
        data = super().validate(attrs)
        user = self.user
        data["role"] = user.role
        data["user"] = UserSerializer(user, context=self.context).data
        return data


class AuthResponseSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
    role = serializers.ChoiceField(choices=Role.choices)
    user = UserSerializer()


class PasswordChangeSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True, trim_whitespace=False)
    new_password = serializers.CharField(write_only=True, trim_whitespace=False)


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True, trim_whitespace=False)


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class AddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = Address
        fields = (
            "id",
            "label",
            "line1",
            "line2",
            "city",
            "notes",
            "lat",
            "lng",
            "is_default",
            "created_at",
        )
        read_only_fields = ("id", "created_at")


class DeviceTokenSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeviceToken
        fields = ("id", "token", "platform", "is_active", "created_at")
        read_only_fields = ("id", "is_active", "created_at")

    def create(self, validated_data):
        request = self.context["request"]
        token, _ = self.Meta.model.objects.update_or_create(
            token=validated_data["token"],
            defaults={
                "user": request.user,
                "platform": validated_data.get("platform", "android"),
                "is_active": True,
            },
        )
        return token
