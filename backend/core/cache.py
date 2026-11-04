"""Cache validators for the anonymous catalog.

The public storefront reads are the only part of this API a shared cache may
store: they are anonymous, they change slowly, and they are the busiest
endpoints on the box. Without `Cache-Control` every visit is a full round trip,
and without an `ETag` a returning visitor cannot even ask "has this changed?".

Deliberately not a middleware: a global ETag would also land on authenticated
responses, where a browser may replay one user's order list for the next user
at the same URL. Only the views that opt in are cacheable, and they are all
anonymous.
"""

import hashlib

from django.utils.cache import get_conditional_response


class PublicCacheMixin:
    """`Cache-Control` plus a content `ETag`, answered with `304` when it matches.

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
