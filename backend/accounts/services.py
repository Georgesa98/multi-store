"""Account business logic. Views validate and call these, nothing else."""

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from rest_framework.exceptions import ValidationError
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Address, CustomerProfile
from core.enums import Role

User = get_user_model()


def issue_tokens(user) -> dict[str, str]:
    refresh = RefreshToken.for_user(user)
    return {"refresh": str(refresh), "access": str(refresh.access_token)}


@transaction.atomic
def register_customer(*, email, password, full_name, phone=""):
    if User.objects.filter(email__iexact=email).exists():
        raise ValidationError({"email": ["An account with this email already exists."]})
    user = User.objects.create_user(
        email=email,
        password=password,
        full_name=full_name,
        phone=phone,
        role=Role.CUSTOMER,
    )
    CustomerProfile.objects.create(user=user)
    return user


def change_password(*, user, new_password, old_password=None, skip_old_password=False):
    if not skip_old_password and not user.check_password(old_password or ""):
        raise ValidationError({"old_password": ["Current password is incorrect."]})
    try:
        validate_password(new_password, user=user)
    except DjangoValidationError as exc:
        raise ValidationError({"new_password": list(exc.messages)}) from exc
    user.set_password(new_password)
    user.save(update_fields=["password"])
    blacklist_all_tokens(user)
    return user


def blacklist_all_tokens(user) -> None:
    """Invalidate every outstanding refresh token for a user."""
    from rest_framework_simplejwt.token_blacklist.models import (
        BlacklistedToken,
        OutstandingToken,
    )

    for token in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=token)


def make_password_reset_token(user) -> tuple[str, str]:
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    return uid, default_token_generator.make_token(user)


def resolve_password_reset_token(uidb64: str, token: str):
    try:
        user = User.objects.get(pk=force_str(urlsafe_base64_decode(uidb64)))
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        return None
    if not default_token_generator.check_token(user, token):
        return None
    return user


def send_invite(user, organization=None) -> None:
    """Invite email for a newly onboarded store or delivery-company account."""
    from django.conf import settings
    from django.core.mail import send_mail

    uid, token = make_password_reset_token(user)
    url = f"{settings.FRONTEND_URL}/reset-password?uid={uid}&token={token}"
    where = f" for {organization.name}" if organization is not None else ""
    send_mail(
        subject="You have been invited",
        message=f"Set your password to activate your account{where}: {url}",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=True,
    )


# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------


@transaction.atomic
def create_address(*, customer, **data) -> Address:
    if data.get("is_default"):
        Address.objects.filter(customer=customer).update(is_default=False)
    return Address.objects.create(customer=customer, **data)


@transaction.atomic
def update_address(address: Address, **data) -> Address:
    if data.get("is_default") is True:
        Address.objects.filter(customer=address.customer).exclude(pk=address.pk).update(
            is_default=False
        )
    for key, value in data.items():
        setattr(address, key, value)
    address.save()
    return address


@transaction.atomic
def set_default_address(address: Address) -> Address:
    Address.objects.filter(customer=address.customer).exclude(pk=address.pk).update(
        is_default=False
    )
    address.is_default = True
    address.save(update_fields=["is_default", "updated_at"])
    return address
