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
    python manage.py migrate --noinput
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
