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
`backend/Dockerfile`.

```powershell
Copy-Item .env.example .env    # then fill SECRET_KEY, POSTGRES_PASSWORD, DOCS_AUTH_PASSWORD
$env:SECURE_SSL_REDIRECT="False"   # the committed .env is set for https
docker compose -f docker-compose.yml -f docker-compose.local.yml up --build
# API    http://localhost:8010/api/v1/
# Docs   http://localhost:8010/api/docs/     basic auth from .env
# Health http://localhost:8010/healthz/
```

The base file publishes no host port, because in production Coolify's Traefik
owns the ingress and a leftover host port collides with it. The `local` override
adds the `8010:8000` mapping that makes the URLs above true — 8010 rather than
8000 because `runserver` already owns 8000 on a developer machine.

`SECRET_KEY` and `POSTGRES_PASSWORD` are declared `${VAR:?}` in the compose file,
so a deploy that leaves either empty stops with an error instead of running with
a default. `.env.example` ships both empty on purpose.

The same file is the deploy artifact, already pointed at
**https://multi-store.georgesalebe.me**: on Coolify create a **Docker Compose**
resource from this repository, keep the compose path at `/docker-compose.yml`,
paste the variables from `.env.example`, and under **Domains** add

```
https://multi-store.georgesalebe.me:8000
```

for the **`api`** service. The `:8000` is the internal container port Coolify
routes to — public requests still arrive on 443, so the URL in the address bar
has no port. Coolify's docs say not to publish `ports:` for a proxied service,
which is why the mapping lives in `docker-compose.local.yml` instead.

That `:8000` is also a common misreading: it is **not** a public port. On a
Coolify host, port 8000 is the Coolify dashboard itself — `http://<host>:8000`
opens Coolify's login, never this API. `ALLOWED_HOSTS` carries the hostname plus
loopback so the container's own healthcheck is not a `DisallowedHost`,
migrations run at container start, and uploads live in the `media` volume, which
must survive deploys.

One image, three commands (`backend/docker-entrypoint.sh`):

| Role | Command | Does |
|---|---|---|
| `api` | `api` | `migrate`, `collectstatic`, daphne on `:8000` (ASGI — the tracking socket needs it) |
| worker | `worker` | `celery -A config worker -l info` |
| beat | `beat` | `celery -A config beat -l info` |

Static files are served by WhiteNoise from the same container, so the docs page
needs no Nginx and no second deploy.

### Changing the database password

Postgres reads `POSTGRES_PASSWORD` **once**, when it initialises an empty data
directory. The password is a property of the `pgdata` volume after that, so
editing the variable and redeploying leaves the api crash-looping on
`password authentication failed` while the db container still reports healthy —
the healthcheck logs in with the same credentials, so it now fails too, which is
the point: the database is the thing that reports the problem.

Change it where it lives, then restart the api:

```bash
docker exec -it <db-container> \
  psql -U multistore -d multistore \
  -c "ALTER USER multistore WITH PASSWORD 'new-password'"
```

On a first deploy with nothing worth keeping, deleting the `pgdata` volume and
redeploying is simpler and exercises the real first-boot path. The `media` and
`redisdata` volumes are untouched by either route. Keep the password to
`A-Za-z0-9`: it is interpolated straight into `DATABASE_URL`, where `@ : / ? #`
would break the connection string.

## Testing

`python -m pytest` runs the suite against Postgres using
`config.settings.test` (in-memory channel layer, eager Celery), so no broker or
Redis is needed. `tests/test_tenancy.py` asserts that every dashboard, company
and courier endpoint answers `404` across tenants; keep that green when adding
endpoints. `tests/test_docs.py` fails when `schema.yml` drifts from the code —
the reference page would otherwise describe an API that no longer exists.
