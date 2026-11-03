# Multi-Store Marketplace + Delivery

A multi-store marketplace with cash-on-delivery fulfilment. A customer holds
carts from several stores at once and checks out in one action; checkout
produces one `CheckoutGroup` and one order per store. Delivery companies
onboard as tenants, publish radius-based zones and dispatch their own couriers.

This repository is the whole product:

| Path | What | Stack |
|---|---|---|
| `backend/` | REST API, dispatch, tracking socket, background jobs | Python 3.14, Django 6, DRF, Celery, Channels |
| `apps/store_web/` | Store, delivery-company and platform dashboards | React (planned) |
| `apps/customer_app/` | Customer app | Flutter (planned) |
| `apps/courier_app/` | Courier app | Flutter (planned) |

The API is authoritative: `backend/schema.yml` is the contract every client
generates its types from. `backend/AGENTS.md` holds the product rules and the
data model.

## Prerequisites

- Python 3.12+ (this checkout runs 3.14)
- PostgreSQL 16 — this developer's instance runs in WSL and listens on
  **port 5433**, because a native Windows cluster already owns 5432
- Redis (WSL is fine) for Celery and the channel layer

## First run

From the repository root:

```powershell
python -m venv backend\.venv
backend\.venv\Scripts\Activate.ps1
pip install -r backend\requirements-dev.txt

Copy-Item backend\.env.example backend\.env
# edit DATABASE_URL, REDIS_URL and CORS_ALLOWED_ORIGINS
```

Create the database once (the role needs `CREATEDB` so the test database can be
made):

```bash
sudo -u postgres psql -c "CREATE ROLE george LOGIN PASSWORD '...' CREATEDB;"
sudo -u postgres psql -c "CREATE DATABASE multistore OWNER george;"
```

Then, from `backend/`:

```powershell
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
```

## Everyday commands

| Task | Command (from `backend/`) |
|---|---|
| API | `python manage.py runserver` |
| Worker | `celery -A config worker -l info` |
| Beat (rollups, payouts, stale orders, ping pruning) | `celery -A config beat -l info` |
| Tests | `python -m pytest` |
| Lint / format | `ruff check .` · `ruff format .` |
| Migrations | `python manage.py makemigrations <app>` · `python manage.py migrate` |
| Regenerate the contract | `python manage.py spectacular --file schema.yml` |
| Demo data | `python manage.py seed_demo` |
| Roll up a day | `python manage.py rollup_stats --from YYYY-MM-DD --to YYYY-MM-DD` |
| Materialise a payout week | `python manage.py materialise_payouts --week YYYY-MM-DD` |

## API

- Base path `/api/v1/`, one module per surface: `auth`, `public`, `dashboard`,
  `company`, `courier`, `platform`.
- Reference at `/api/docs/` (Scalar), Swagger UI at `/api/docs/swagger/`,
  ReDoc at `/api/redoc/`, raw schema at `/api/schema/` and in
  `backend/schema.yml`.
- Those four routes are behind a shared credential (`DOCS_AUTH_USER` /
  `DOCS_AUTH_PASSWORD`). Empty in development means open; empty in production
  means 404. Fetch the contract from a script with
  `curl -u "$DOCS_AUTH_USER:$DOCS_AUTH_PASSWORD" https://host/api/schema/`.
- JWT access tokens last 15 minutes, refresh tokens 7 days with rotation and
  blacklist; send `Authorization: Bearer <access>`.
- Every list endpoint is paginated: `?page=&page_size=` → `{count, next,
  previous, results}` (default 20, max 100).
- Money is a string (`"125000.00"`), ids are UUID strings, timestamps are
  ISO-8601 UTC.
- Errors: `{"detail": "..."}` or `{"field": ["..."]}`; `409` illegal state
  change, `422` business rule, `404` for anything belonging to another tenant.

## Deploying (Docker Compose / Coolify)

`docker-compose.yml` at the repository root runs the whole stack — Postgres 16,
Redis, the API, a Celery worker and beat — from one image built by
`backend/Dockerfile`. Nothing publishes a host port: a proxy (Coolify's Traefik
in production, `docker compose` locally) is what the browser talks to.

```powershell
Copy-Item .env.example .env    # set SECRET_KEY, POSTGRES_PASSWORD, DOCS_AUTH_PASSWORD
$env:SECURE_SSL_REDIRECT="False"   # the committed .env is set for https
docker compose up --build
# API    http://localhost:8000/api/v1/
# Docs   http://localhost:8000/api/docs/     basic auth from .env
# Health http://localhost:8000/healthz/
```

The same file is the deploy artifact, already pointed at
**https://multi-store.georgesalebe.me**: on Coolify create a **Docker Compose**
resource from this repository, keep the compose path at `/docker-compose.yml`,
paste the variables from `.env.example`, and attach that domain to the `api`
service on port 8000. `ALLOWED_HOSTS` carries the hostname plus loopback so the
container's own healthcheck is not a `DisallowedHost`, migrations run at
container start, and uploads live in
the `media` volume, which must survive deploys.

One image, three commands (`backend/docker-entrypoint.sh`):

| Role | Command | Does |
|---|---|---|
| `api` | `api` | `migrate`, `collectstatic`, daphne on `:8000` (ASGI — the tracking socket needs it) |
| worker | `worker` | `celery -A config worker -l info` |
| beat | `beat` | `celery -A config beat -l info` |

Static files are served by WhiteNoise from the same container, so the docs page
needs no Nginx and no second deploy.

## Testing

`python -m pytest` runs the suite against Postgres using
`config.settings.test` (in-memory channel layer, eager Celery), so no broker or
Redis is needed. `tests/test_tenancy.py` asserts that every dashboard, company
and courier endpoint answers `404` across tenants; keep that green when adding
endpoints. `tests/test_docs.py` fails when `schema.yml` drifts from the code —
the reference page would otherwise describe an API that no longer exists.
