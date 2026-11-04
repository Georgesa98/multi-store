"""Production settings.

Django admin is disabled: it is not a product surface. Platform capability is
exposed through /api/v1/platform/ only.
"""

from .base import *  # noqa: F403
from .base import env

DEBUG = False

ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")

# The reverse proxy terminates TLS; these are the origins allowed to POST.
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# Static files (the Scalar bundle, admin assets) are served by WhiteNoise so a
# single container is enough — no Nginx sidecar, no separate CDN step.
MIDDLEWARE = list(MIDDLEWARE)  # noqa: F405
MIDDLEWARE.insert(
    MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1,
    "whitenoise.middleware.WhiteNoiseMiddleware",
)

# Security
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
# The container healthcheck speaks plain HTTP to itself; keep it out of the
# redirect or Docker marks a perfectly healthy container as unhealthy.
SECURE_REDIRECT_EXEMPT = [r"^healthz/$"]
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# No browsable API in production.
REST_FRAMEWORK = {  # noqa: F405
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_RENDERER_CLASSES": ("rest_framework.renderers.JSONRenderer",),
}

# Rate-limit counters are shared state: with LocMem, several api containers
# would each allow a full budget and a client could multiply its allowance by
# chance. The backend fails open, so a Redis outage degrades the limiter
# instead of taking every endpoint down with it.
CACHES = {
    "default": {
        "BACKEND": "core.cache.TolerantRedisCache",
        "LOCATION": REDIS_URL,  # noqa: F405
    }
}

# Admin routes are not mounted at all (see config/urls.py); removing the app
# from INSTALLED_APPS would also drop admin autodiscovery checks, which is fine.

# Every line carries the request id, so the identifier a user quotes from an
# error body finds the traceback in the container log.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {
            "format": "{levelname} {asctime} {name} [{request_id}] {message}",
            "style": "{",
        },
    },
    "filters": {"request_id": {"()": "core.middleware.RequestIDLogFilter"}},
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "plain",
            "filters": ["request_id"],
        },
    },
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}
