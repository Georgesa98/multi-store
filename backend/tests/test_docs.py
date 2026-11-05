"""The docs surfaces, and the promise that they describe this build.

Three things are asserted here: the gate behaves (open in DEBUG, closed and
credentialled elsewhere), the reference page actually renders the contract, and
the committed `schema.yml` still matches what the code generates — because a
docs page that describes a different API is worse than no docs page.
"""

import base64
import json
from pathlib import Path

import pytest
import yaml
from django.conf import settings
from django.contrib.staticfiles import finders
from django.test import override_settings
from drf_spectacular.generators import SchemaGenerator

from config.api_tags import TAG_GROUPS
from config.api_text import OPERATIONS

GATED = ("/api/docs/", "/api/docs/swagger/", "/api/schema/", "/api/redoc/")

CREDENTIALS = {"DOCS_AUTH_USER": "docs", "DOCS_AUTH_PASSWORD": "s3cret"}


def basic(user="docs", password="s3cret"):
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"HTTP_AUTHORIZATION": f"Basic {token}"}


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


@override_settings(DOCS_AUTH_USER="", DOCS_AUTH_PASSWORD="", DEBUG=True)
def test_docs_are_open_in_debug_without_a_credential(client):
    assert client.get("/api/docs/").status_code == 200


def test_docs_credential_settings_are_declared():
    # The middleware reads these off settings; a missing declaration is a 500
    # on every docs request, not an ImportError at startup.
    assert hasattr(settings, "DOCS_AUTH_USER")
    assert hasattr(settings, "DOCS_AUTH_PASSWORD")


@override_settings(DOCS_AUTH_USER="", DOCS_AUTH_PASSWORD="", DEBUG=False)
def test_docs_do_not_exist_in_production_without_a_credential(client):
    for url in GATED:
        assert client.get(url).status_code == 404, url


@override_settings(DEBUG=False, **CREDENTIALS)
def test_docs_ask_for_credentials(client):
    response = client.get("/api/docs/")
    assert response.status_code == 401
    assert response["WWW-Authenticate"].startswith("Basic ")


@override_settings(DEBUG=False, **CREDENTIALS)
@pytest.mark.parametrize("url", GATED)
def test_docs_reject_the_wrong_password(client, url):
    assert client.get(url, **basic(password="wrong")).status_code == 401


@override_settings(DEBUG=False, **CREDENTIALS)
@pytest.mark.parametrize("url", GATED)
def test_docs_accept_the_shared_credential(client, url):
    assert client.get(url, **basic()).status_code == 200


@override_settings(DEBUG=False, **CREDENTIALS)
def test_api_is_not_behind_the_docs_gate(client):
    # 405 proves the request reached the view; the gate would have said 401.
    assert client.get("/api/v1/auth/register/").status_code == 405


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------


@override_settings(DOCS_AUTH_USER="", DOCS_AUTH_PASSWORD="", DEBUG=True)
def test_reference_page_embeds_the_contract(client):
    response = client.get("/api/docs/")
    html = response.content.decode()
    assert "vendor/scalar-1.76.4.js" in html
    # An operation id from the embedded schema, not from a second fetch.
    assert "auth_register_create" in html


def test_scalar_bundle_is_where_collectstatic_will_find_it():
    assert finders.find("vendor/scalar-1.76.4.js") is not None


# ---------------------------------------------------------------------------
# The contract
# ---------------------------------------------------------------------------


def test_committed_schema_matches_the_code():
    generated = SchemaGenerator().get_schema(request=None, public=True)
    committed = yaml.safe_load((Path(settings.BASE_DIR) / "schema.yml").read_text(encoding="utf-8"))
    assert json.dumps(generated, sort_keys=True, default=str) == json.dumps(
        committed, sort_keys=True, default=str
    ), "schema.yml is stale: run `python manage.py spectacular --file schema.yml`"


# ---------------------------------------------------------------------------
# The endpoint text
# ---------------------------------------------------------------------------


def _live_operations():
    schema = SchemaGenerator().get_schema(request=None, public=True)
    return {
        (method.upper(), path): operation
        for path, methods in schema["paths"].items()
        for method, operation in methods.items()
        if method in ("get", "post", "put", "patch", "delete")
    }


def test_every_operation_is_in_the_text_table():
    live = set(_live_operations())
    described = set(OPERATIONS)

    assert not live - described, (
        f"endpoints with no summary or description: {sorted(live - described)}"
    )
    assert not described - live, (
        f"table entries for paths that no longer exist: {sorted(described - live)}"
    )


def test_operation_text_matches_the_schema():
    for key, operation in _live_operations().items():
        assert operation.get("summary") == OPERATIONS[key].summary, key
        assert operation.get("description") == OPERATIONS[key].description, key


def test_operation_text_fits_a_reference_card():
    # Scalar prints the summary as the operation label and the description under
    # it; anything longer wraps into a wall of text in the sidebar.
    for key, text in OPERATIONS.items():
        assert 0 < len(text.summary) <= 60, key
        assert 0 < len(text.description) <= 240, key


# ---------------------------------------------------------------------------
# The sidebar
# ---------------------------------------------------------------------------


def test_every_tag_is_declared_used_and_grouped_exactly_once():
    schema = SchemaGenerator().get_schema(request=None, public=True)
    declared = [tag["name"] for tag in schema.get("tags", [])]

    used = {tag for operation in _live_operations().values() for tag in operation.get("tags", [])}
    grouped = [tag for group in schema.get("x-tagGroups", []) for tag in group["tags"]]

    assert not used - set(declared), f"tags without a description: {sorted(used - set(declared))}"
    assert not set(declared) - used, (
        f"declared tags with no operations: {sorted(set(declared) - used)}"
    )
    assert sorted(grouped) == sorted(declared), (
        "x-tagGroups must name every declared tag exactly once, because Scalar "
        f"hides any tag no group names; groups: {grouped}"
    )


def test_tag_groups_are_the_surfaces_in_order():
    # The page reads top to bottom in this order, and the test above proves the
    # groups cover the tags; this one keeps the reading order from drifting.
    assert [group["name"] for group in TAG_GROUPS] == [
        "Authentication",
        "Storefront",
        "Store dashboard",
        "Delivery company",
        "Courier",
        "Platform",
    ]


@pytest.mark.django_db
def test_healthz_answers(client):
    response = client.get("/healthz/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
