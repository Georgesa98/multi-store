"""Permission classes. Every view must declare one explicitly."""

from rest_framework.permissions import BasePermission

from core.enums import Role


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
    """Read access to `/api/v1/dashboard/`."""

    allowed_roles = (Role.STORE_ADMIN, Role.STORE_STAFF)


class IsDashboardWriter(HasRole):
    """Write access to `/api/v1/dashboard/` (staff is read-only)."""

    allowed_roles = (Role.STORE_ADMIN,)
