#!/bin/sh
# Entrypoint for every container built from this image.
#
#   api     migrate, collect static, serve ASGI (REST + the tracking socket)
#   worker  Celery worker
#   beat    Celery beat
#   <cmd>   anything else, run as-is (e.g. `python manage.py seed_demo`)

set -eu

role="${1:-api}"

case "$role" in
  api)
    # Workers start after the api container is healthy (see compose), so a
    # single migrator is enough; migrations are idempotent anyway.
    if ! python manage.py migrate --noinput; then
      # The traceback above names the real error. This is the one cause that
      # looks like a code bug and is not: Postgres reads POSTGRES_PASSWORD only
      # when its data directory is empty, so a volume that outlives a password
      # change holds the old one forever.
      cat >&2 <<'EOM'

The database refused this container. If the error above says "password
authentication failed for user ...", the pgdata volume still holds the password
it was created with: POSTGRES_PASSWORD is read only when that volume is empty,
so editing the variable afterwards changes what Django sends, not what Postgres
expects. Either set POSTGRES_PASSWORD back to the old value, or change it where
it actually lives:

  docker exec -it <db-container> psql -U <user> -d <db> \
    -c "ALTER USER <user> WITH PASSWORD '<new-password>'"

A first deploy with nothing worth keeping can instead delete the pgdata volume
and start again.

EOM
      exit 1
    fi
    python manage.py collectstatic --noinput --verbosity 0
    exec daphne -b 0.0.0.0 -p "${PORT:-8000}" config.asgi:application
    ;;
  worker)
    exec celery -A config worker -l info
    ;;
  beat)
    exec celery -A config beat -l info
    ;;
  *)
    exec "$@"
    ;;
esac
