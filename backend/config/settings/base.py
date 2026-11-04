"""Base settings shared by every environment.

Environment-specific modules (`dev.py`, `prod.py`) import from here and only
override what differs. Everything configurable comes from the environment.
"""

from datetime import timedelta
from pathlib import Path

import environ
from celery.schedules import crontab

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    SECRET_KEY=(str, "dev-only-insecure-secret-key-change-me"),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    CORS_ALLOWED_ORIGINS=(list, []),
    DATABASE_URL=(str, "postgres://postgres:postgres@127.0.0.1:5432/multistore"),
    REDIS_URL=(str, "redis://127.0.0.1:6379/0"),
    DOCS_AUTH_USER=(str, ""),
    DOCS_AUTH_PASSWORD=(str, ""),
)
environ.Env.read_env(BASE_DIR / ".env")

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

# Shared credential for /api/docs/, /api/schema/ and /api/redoc/. Empty in
# development means "open"; empty in production means "not there". See
# core.middleware.DocsGateMiddleware.
DOCS_AUTH_USER = env("DOCS_AUTH_USER")
DOCS_AUTH_PASSWORD = env("DOCS_AUTH_PASSWORD")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
    "django_filters",
    "corsheaders",
    "channels",
    # Local
    "core",
    "accounts",
    "stores",
    "catalog",
    "cart",
    "orders",
    "delivery",
    "notifications",
    "reviews",
    "analytics",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # Correlates a response, its log lines and an error report.
    "core.middleware.RequestIDMiddleware",
    # Keeps the docs surfaces behind a shared credential outside DEBUG.
    "core.middleware.DocsGateMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ---------------------------------------------------------------------------
# Database / cache / async
# ---------------------------------------------------------------------------

DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["CONN_MAX_AGE"] = env.int("CONN_MAX_AGE", default=60)

REDIS_URL = env("REDIS_URL", default="redis://127.0.0.1:6379/0")

# Throttle counters live in the cache, so every api container must count the
# same requests: production points this at Redis (see prod.py). LocMem is the
# development fallback and is correct for one process.
CACHES = {
    "default": {
        "BACKEND": env("CACHE_BACKEND", default="django.core.cache.backends.locmem.LocMemCache"),
        "LOCATION": env("CACHE_LOCATION", default="multistore"),
    }
}

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [REDIS_URL]},
    }
}

CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default=None)
CELERY_TASK_ALWAYS_EAGER = False
CELERY_TIMEZONE = "UTC"
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60

CELERY_BEAT_SCHEDULE = {
    "cancel-stale-pending-orders": {
        "task": "orders.tasks.cancel_stale_pending_orders",
        "schedule": 5 * 60,
    },
    "rollup-daily-stats": {
        "task": "analytics.tasks.rollup_daily_stats",
        # 00:15 in the reporting zone; the task itself pins the day.
        "schedule": crontab(hour=0, minute=15),
    },
    "materialise-payouts": {
        "task": "analytics.tasks.materialise_payouts",
        # Monday 00:30: roll the week that just ended into settlement rows.
        "schedule": crontab(hour=0, minute=30, day_of_week=1),
    },
    "prune-location-pings": {
        "task": "delivery.tasks.prune_location_pings",
        # Sunday 03:00: the trail is a trail, not history.
        "schedule": crontab(hour=3, minute=0, day_of_week=0),
    },
}

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

# ---------------------------------------------------------------------------
# DRF / OpenAPI / filters
# ---------------------------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    # Default-deny. Every view still declares its own permission class.
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_PAGINATION_CLASS": "core.pagination.StandardResultsSetPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        # No global SearchFilter: no view declares `search_fields`, so it only
        # advertised a `search` parameter that filtered nothing. Search is `q`,
        # implemented per view.
        "rest_framework.filters.OrderingFilter",
    ),
    # Rate limits. Named scopes keep a busy catalog session from eating the
    # budget for login or checkout; `core.throttling.ScopedThrottleMixin`
    # applies a view's scope on top of the two global buckets. Every rate is an
    # environment override because the right number depends on traffic.
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "anon": env("THROTTLE_ANON", default="60/min"),
        "user": env("THROTTLE_USER", default="300/min"),
        "auth": env("THROTTLE_AUTH", default="20/min"),
        "password-reset": env("THROTTLE_PASSWORD_RESET", default="5/hour"),
        "checkout": env("THROTTLE_CHECKOUT", default="20/min"),
        "checkout-preview": env("THROTTLE_CHECKOUT_PREVIEW", default="60/min"),
        "quote": env("THROTTLE_QUOTE", default="60/min"),
        "ticket": env("THROTTLE_TICKET", default="30/min"),
        "location": env("THROTTLE_LOCATION", default="120/min"),
        "review": env("THROTTLE_REVIEW", default="20/hour"),
        "invite": env("THROTTLE_INVITE", default="20/hour"),
    },
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    # Object-level errors answer `{"detail": ..., "code": ...}`; field
    # validation keeps DRF's `{"field": [...]}` shape. See core.handlers.
    "EXCEPTION_HANDLER": "core.handlers.api_exception_handler",
    "COERCE_DECIMAL_TO_STRING": True,
    "DEFAULT_RENDERER_CLASSES": ("rest_framework.renderers.JSONRenderer",),
    "DATETIME_FORMAT": "%Y-%m-%dT%H:%M:%S.%fZ",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Multi-Store Marketplace & Delivery API",
    "DESCRIPTION": (
        "Customer, store dashboard, courier and platform surfaces for a "
        "multi-store marketplace with per-store cash-on-delivery fulfilment.\n\n"
        'Errors answer `{"detail": ..., "code": ...}` for object-level '
        "failures; `code` is stable, so branch on it rather than the prose. "
        "`409` is an illegal state transition, `422` a broken business rule "
        "(stock, minimum order, zone), `429` throttling. Field validation "
        'keeps DRF\'s `{"field": ["..."]}` shape with no top-level `code`.'
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SORT_OPERATIONS": False,
    "SCHEMA_PATH_PREFIX": "/api/v1",
    # Every operation's summary and description lives in one table, so the
    # reference page reads consistently and a missing one fails a test instead
    # of shipping as a bare path. See `config/api_text.py`.
    "POSTPROCESSING_HOOKS": [
        "config.api_errors.apply_error_responses",
        "config.api_text.apply_operation_text",
    ],
    "ENUM_NAME_OVERRIDES": {
        # Several models reuse `role` and `status` field names with different
        # choice sets; name each explicitly so components stay stable.
        "RoleEnum": "core.enums.Role",
        "MemberRoleEnum": "core.enums.MemberRole",
        "StoreStatusEnum": "core.enums.StoreStatus",
        # `CompanyStatus` shares its choice set with `StoreStatus` (pending,
        # active, suspended, closed), so the schema reuses the one component
        # name; drf-spectacular rejects two names for identical choices.
        "ProductStatusEnum": "core.enums.ProductStatus",
        "OrderStatusEnum": "core.enums.OrderStatus",
        "PaymentStatusEnum": "core.enums.PaymentStatus",
        "DeliveryStatusEnum": "core.enums.DeliveryStatus",
        "DeliveryActionEnum": "core.enums.DeliveryAction",
        "CouponTypeEnum": "core.enums.CouponType",
    },
    "TAGS": [
        {"name": "auth", "description": "Authentication and account self-service"},
        {
            "name": "customer",
            "description": "Browsing, carts and checkout for the signed-in customer",
        },
        {
            "name": "orders",
            "description": "The customer's own orders, timeline and cancellation",
        },
        {
            "name": "dashboard",
            "description": "The store dashboard: catalog, orders, partners, insights",
        },
        {
            "name": "company",
            "description": "The delivery company dashboard: team, riders, zones, dispatch",
        },
        {
            "name": "courier",
            "description": "The courier app: offers, deliveries, location, COD",
        },
        {
            "name": "delivery",
            "description": "Dispatch jobs and their events across stores and companies",
        },
        {
            "name": "platform",
            "description": "Super admin: onboarding, suspensions, payouts, platform insights",
        },
    ],
}

# ---------------------------------------------------------------------------
# Internationalisation / static / media
# ---------------------------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Dashboards bucket a day by this zone, not by UTC. The DB stays UTC.
REPORT_TIME_ZONE = env("REPORT_TIME_ZONE", default="Asia/Damascus")

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# Vendored assets (the Scalar bundle behind /api/docs/) live outside the apps.
STATICFILES_DIRS = [BASE_DIR / "static"]

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # No manifest: the docs page must work in DEBUG without a collectstatic run.
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

# ---------------------------------------------------------------------------
# CORS / email
# ---------------------------------------------------------------------------

CORS_ALLOWED_ORIGINS = env("CORS_ALLOWED_ORIGINS")
CORS_ALLOW_CREDENTIALS = True

EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="no-reply@multi-store.local")

# Where password-reset links point (customer web/app deep link).
FRONTEND_URL = env("FRONTEND_URL", default="http://localhost:5173")

# ---------------------------------------------------------------------------
# Project constants
# ---------------------------------------------------------------------------

DEFAULT_CURRENCY = "SYP"
