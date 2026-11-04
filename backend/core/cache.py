"""Cache behaviour: public validators and the fault-tolerant counter cache."""

import hashlib

from django.core.cache.backends.base import DEFAULT_TIMEOUT
from django.core.cache.backends.redis import RedisCache
from django.utils.cache import get_conditional_response
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError


class TolerantRedisCache(RedisCache):
    """Redis counters that fail open.

    Throttling must never be the reason a request answers 500: if the cache is
    unreachable, the limiter sees an empty history, allows the request, and
    counts again once Redis is back. Without this, a Redis restart would take
    the whole API down even though only the rate-limit counters use it.
    """

    _OUTAGE = (RedisConnectionError, RedisTimeoutError)

    def get(self, key, default=None, version=None):
        try:
            return super().get(key, default=default, version=version)
        except self._OUTAGE:
            return default

    def set(self, key, value, timeout=DEFAULT_TIMEOUT, version=None):
        try:
            return super().set(key, value, timeout=timeout, version=version)
        except self._OUTAGE:
            return False

    def add(self, key, value, timeout=DEFAULT_TIMEOUT, version=None):
        try:
            return super().add(key, value, timeout=timeout, version=version)
        except self._OUTAGE:
            return False

    def incr(self, key, delta=1, version=None):
        try:
            return super().incr(key, delta=delta, version=version)
        except self._OUTAGE:
            return None

    def delete(self, key, version=None):
        try:
            return super().delete(key, version=version)
        except self._OUTAGE:
            return False

    def touch(self, key, timeout=DEFAULT_TIMEOUT, version=None):
        try:
            return super().touch(key, timeout=timeout, version=version)
        except self._OUTAGE:
            return False


class PublicCacheMixin:
    """`Cache-Control` plus a content `ETag`, answered with `304` when it matches.

    Only the anonymous storefront reads opt in. Deliberately not a middleware:
    a global ETag would also land on authenticated responses, where a browser
    may replay one user's order list for the next user at the same URL.

    Sits on a DRF view: `finalize_response` is the first point where the
    renderer, the status code and the body are all known.
    """

    cache_max_age = 60

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)

        if request.method != "GET" or response.status_code != 200:
            return response

        response["Cache-Control"] = (
            f"public, max-age={self.cache_max_age}, stale-while-revalidate={self.cache_max_age}"
        )

        if not response.has_header("ETag"):
            response.render()
            digest = hashlib.sha256(response.content).hexdigest()[:32]
            response["ETag"] = f'"{digest}"'

        return get_conditional_response(request, etag=response["ETag"], response=response)
