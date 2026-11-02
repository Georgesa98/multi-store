"""Development settings: local Postgres/Redis over WSL, verbose errors."""

from .base import *  # noqa: F403
from .base import BASE_DIR, env

DEBUG = env.bool("DEBUG", default=True)

ALLOWED_HOSTS = ["*"]

# Serve uploaded media from the dev server.
MEDIA_ROOT = BASE_DIR / "media"

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "[{asctime}] {levelname} {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.db.backends": {"level": "INFO", "handlers": ["console"], "propagate": False},
    },
}
