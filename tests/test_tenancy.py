"""Tenancy guardrails.

Phase 0 covers store resolution; Phase 1 extends this to every dashboard and
courier endpoint: a store admin touching another store's object gets 404,
never 403, so object existence never leaks.
"""

from django.contrib.auth import get_user_model

from core.enums import Role
from core.tenancy import resolve_store_id

User = get_user_model()


def test_customer_has_no_store(db, customer):
    assert resolve_store_id(customer) is None


def test_super_admin_resolves_to_no_store_but_is_unscoped(db, super_admin):
    # Super admin sees everything through `for_user`, which short-circuits on
    # the role before asking for a store id.
    assert resolve_store_id(super_admin) is None
    assert super_admin.role == Role.SUPER_ADMIN


def test_anonymous_user_has_no_store():
    from django.contrib.auth.models import AnonymousUser

    assert resolve_store_id(AnonymousUser()) is None
