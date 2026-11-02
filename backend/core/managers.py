"""QuerySet/manager that can never return another store's rows."""

from django.db import models

from core.tenancy import resolve_store_id


class StoreScopedQuerySet(models.QuerySet):
    def for_user(self, user):
        """Rows the user may see: everything for super admins, one store otherwise."""
        role = getattr(user, "role", None)
        if role == "super_admin":
            return self
        store_id = resolve_store_id(user)
        if not store_id:
            return self.none()
        return self.filter(store_id=store_id)

    def for_store(self, store):
        store_id = getattr(store, "pk", store)
        return self.filter(store_id=store_id)


class StoreScopedManager(models.Manager.from_queryset(StoreScopedQuerySet)):
    def for_user(self, user):
        return self.get_queryset().for_user(user)

    def for_store(self, store):
        return self.get_queryset().for_store(store)
