# Multi-Store Marketplace — monorepo

The whole product lives here: the Django/DRF API in `backend/`, and — as they
land — the React dashboard and the Flutter apps in `apps/`.

```
backend/   Django + DRF API, Celery workers, and the OpenAPI contract
apps/      the clients: store_web (React), customer_app, courier_app
```

`backend/AGENTS.md` is the product specification and the binding rulebook for
the API. Read it before changing anything under `backend/`; where this file and
that one disagree, `backend/AGENTS.md` wins.

## Ownership

- `backend/` and the repository plumbing belong to the backend team. That is
  where our work happens.
- `apps/` belongs to the frontend developers. Do not scaffold, restyle, or
  "fix" client code unless the task is explicitly about it. If `apps/` is
  missing or empty, nobody has started yet; that is not a gap to fill.
- The contract between the halves is `backend/schema.yml`. Clients generate
  their types from it; nobody hand-writes request or response shapes.

## Running the API

```powershell
# once, from the repository root
python -m venv backend\.venv
backend\.venv\Scripts\Activate.ps1
pip install -r backend\requirements-dev.txt
Copy-Item backend\.env.example backend\.env    # edit DATABASE_URL / REDIS_URL

# every day
cd backend
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
```

Postgres 16 and Redis run outside the repository (this checkout uses WSL;
Postgres listens on **5433** because a native cluster owns 5432). The API is at
`http://127.0.0.1:8000/api/v1/`, the reference at `/api/docs/` (Swagger UI at
`/api/docs/swagger/`), the schema at `/api/schema/`.

Background jobs need their own terminals, from `backend/`:

```powershell
celery -A config worker -l info
celery -A config beat -l info
```

Or run the whole thing in containers, from the repository root:

```powershell
Copy-Item .env.example .env      # edit SECRET_KEY / DOCS_AUTH_PASSWORD
$env:SECURE_SSL_REDIRECT="False" # the committed .env is set for https
docker compose -f docker-compose.yml -f docker-compose.local.yml up --build
```

That brings up Postgres, Redis, the API, a worker and beat, with the API on
`http://localhost:8000/api/v1/` — the base `docker-compose.yml` publishes no
host port because Coolify's Traefik owns the ingress in production, so the
`local` override exists only to add that mapping. The same file is what Coolify
deploys, already pointed at `https://multi-store.georgesalebe.me`; see
`README.md`.

## Checks

From `backend/`:

```powershell
python -m pytest                 # the whole suite, Postgres-backed
ruff check .
ruff format --check .
python manage.py check
python manage.py spectacular --file schema.yml   # regenerate the contract
```

A change to an endpoint is not finished until `schema.yml` is regenerated and
committed with it. The schema drifting from the code is the one bug the client
teams cannot work around.

## Repository conventions

- One branch per change, merged into `master` by pull request.
- Money is `Decimal`, serialized as a string. Ids are UUID strings.
- Cross-tenant reads answer `404`, never `403`.
- Line endings: LF everywhere except Windows scripts (`.gitattributes`).
