"""Permission classes. Every view must declare one explicitly."""

from rest_framework.permissions import BasePermission

from core.enums import Role
from core.tenancy import resolve_membership


class HasRole(BasePermission):
    """Base class: allow only the listed roles."""

    allowed_roles: tuple[str, ...] = ()
    message = "You do not have permission to perform this action."

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user and user.is_authenticated and user.is_active and user.role in self.allowed_roles
        )


class IsSuperAdmin(HasRole):
    allowed_roles = (Role.SUPER_ADMIN,)


class IsCustomer(HasRole):
    allowed_roles = (Role.CUSTOMER,)


class IsCourier(HasRole):
    allowed_roles = (Role.COURIER,)


class IsStoreAdmin(HasRole):
    allowed_roles = (Role.STORE_ADMIN,)


class IsDashboardUser(HasRole):
    """Read access to `/api/v1/dashboard/`.

    Also resolves `request.store` / `request.membership`. A store admin with no
    active membership gets 403, per section 10.
    """

    allowed_roles = (Role.STORE_ADMIN, Role.STORE_STAFF)

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        membership = resolve_membership(request.user)
        if membership is None:
            return False
        request.membership = membership
        request.store = membership.store
        return True


class IsDashboardWriter(IsDashboardUser):
    """Write access: the `owner`/`manager` membership role, never staff."""

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        return request.membership.can_write


class ReadWritePermissionsMixin:
    """Pick a permission class per method; keeps every view explicit."""

    read_permissions = (IsDashboardUser,)
    write_permissions = (IsDashboardWriter,)

    def get_permissions(self):
        from rest_framework.permissions import SAFE_METHODS

        classes = (
            self.read_permissions if self.request.method in SAFE_METHODS else self.write_permissions
        )
        return [cls() for cls in classes]
