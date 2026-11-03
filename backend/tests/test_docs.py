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


@pytest.mark.django_db
def test_healthz_answers(client):
    response = client.get("/healthz/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
