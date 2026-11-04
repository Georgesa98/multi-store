"""Settings for the test suite: no Redis, no broker.

Everything else is the dev configuration, including the Postgres database, so
the suite runs against the same engine as production.
"""

from .dev import *  # noqa: F403
from .dev import EMAIL_BACKEND, REST_FRAMEWORK  # noqa: F401

CHANNEL_LAYERS = {
    "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"},
}

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# The suite is one client making thousands of requests, so the production
# ceilings would fail tests that have nothing to do with throttling. Keep the
# limits in place (the code path stays exercised) and raise the ceilings; a test
# that wants a 429 patches `SimpleRateThrottle.THROTTLE_RATES` to a low number.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_THROTTLE_RATES": dict.fromkeys(REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"], "100000/min"),
}
