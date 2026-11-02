"""Settings for the test suite: no Redis, no broker.

Everything else is the dev configuration, including the Postgres database, so
the suite runs against the same engine as production.
"""

from .dev import *  # noqa: F403
from .dev import EMAIL_BACKEND  # noqa: F401

CHANNEL_LAYERS = {
    "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"},
}

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
