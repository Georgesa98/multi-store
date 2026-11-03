# Multi-Store API — image for the API and the Celery workers.
#
# One image, three commands (see docker-entrypoint.sh):
#   api     migrations, collectstatic, daphne on :8000
#   worker  celery worker
#   beat    celery beat

FROM python:3.14-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod

WORKDIR /app

# curl is what the compose healthcheck and Docker HEALTHCHECK use.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Dependencies first: editing application code does not refetch them.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home --uid 10001 app \
    && chmod +x docker-entrypoint.sh \
    && chown -R app:app /app
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/healthz/ || exit 1

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["api"]
