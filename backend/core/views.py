"""View mixins shared by the API surfaces."""


class PatchOnlyMixin:
    """Updates are PATCH-only: a detail view routes no PUT, so it answers 405.

    A PUT is a full replacement, and a client that sends only the field the user
    edited silently clears every other writable field. Each detail view here is
    already written as a partial update, so `patch` is the only update method the
    URL conf exposes; `PUT` falls through to DRF's 405 with an `Allow` header
    that names PATCH. See AGENTS.md decision 50.
    """

    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
