# API audit — multi-store backend

An audit of `backend/` as it stands at `7fd8ef7`: 119 paths, 157 operations across
six role surfaces. Findings are ordered by severity, each with the evidence that
produced it and the rule it breaks. The checklist at the end is the work order;
items are ticked as they land, one commit each.

**The count is not the finding.** 157 operations is normal for six audiences
(customer, store dashboard, delivery company, courier, platform, plus auth). The
surfaces are a deliberate BFF split: each audience sees its own projection of the
same rows. What the audit finds is that the published contract is not always
true, the abuse vectors are unguarded, and the cheap naming fixes expire the day
the clients start generating types from `schema.yml`.

## Scoreboard

| Severity | Finding | Count |
|---|---|---|
| critical | No rate limiting anywhere | 0 throttles configured |
| critical | `GET /stores/?ordering=` answers 500 | 1 crashing list |
| critical | Dead `search` parameter advertised | 34 operations |
| high | Documented shape differs from the code | 5 operations |
| high | Errors carry prose, not a machine code | every 4xx/5xx |
| medium | List payloads over-fetch and expose PII | 3 serializers |
| medium | Public store browse filters in Python | 1 view |
| medium | No cache validators on public catalog | 0 ETags |
| low | Naming drift across paths and parameters | 6 cases |
| low | No correlation id on requests or errors | 0 request ids |

## Critical

### C1 — Nothing is throttled

`config/settings/base.py` has a `REST_FRAMEWORK` block with no
`DEFAULT_THROTTLE_CLASSES` and no `DEFAULT_THROTTLE_RATES`, and no view sets
`throttle_classes`. `POST /auth/login/`, `POST /auth/register/`,
`POST /auth/password/reset/`, `POST /checkout/` and the anonymous
`POST /stores/{slug}/delivery-quote/` can be called without limit.

Consequences, in order of likelihood:

- Credential stuffing against `/auth/login/` (email enumeration is already
  mitigated by the generic error, but guessing is free).
- Password-reset mail bombing a third party: the endpoint sends mail to whatever
  address is posted.
- Anonymous load on the quote endpoint, which walks every contracted company and
  runs haversine per zone.
- Checkout spam creating `CheckoutGroup`/`Order`/`Delivery` rows, which also
  consume order numbers from `OrderSequence`.

The fix must answer `429` with `Retry-After`, and the rates must be per-scope so
a burst of catalog browsing does not lock a user out of checkout. `REST_FRAMEWORK`
ships `AnonRateThrottle`, `UserRateThrottle` and `ScopedRateThrottle`; the last
one is the one to use for named buckets. Tests need their own rates in
`config/settings/test.py`, or the suite trips over its own limits.

### C2 — `GET /api/v1/stores/?ordering=` is a 500

`stores/views_public.py:52` returns `list(_visible_stores())`. Every list view
inherits `OrderingFilter` from `DEFAULT_FILTER_BACKENDS`
(`config/settings/base.py:182`), and `OrderingFilter.filter_queryset()` calls
`queryset.model` to validate the field names. A Python list has no `.model`, so
any `?ordering=` — which the schema advertises, because the filter is global —
raises:

```
AttributeError: 'list' object has no attribute 'model'
```

This is a live 500 on the busiest public endpoint, triggered by a parameter the
reference page documents. The same method also filters `q`, `lat`/`lng`/`radius`
and `is_open` in Python after loading every active store, so the crash sits on
top of an unbounded scan.

The fix is to keep a queryset and push what can be pushed into SQL: `q` becomes
`Q(name__icontains=...) | Q(description__icontains=...)`, `is_open` becomes its
weekday/hour predicate, and the radius either stays Python-side (it needs
haversine, there is no PostGIS) or becomes a bounding-box prefilter in SQL. It
must return a queryset regardless, so ordering and pagination work.

### C3 — 34 operations advertise a `search` that filters nothing

The global `SearchFilter` is in `DEFAULT_FILTER_BACKENDS`, so drf-spectacular
documents a `search` query parameter on every list operation. No view sets
`search_fields`, and `SearchFilter` is a no-op without it. Meanwhile `q` is
hand-rolled in five views (`stores/views_public.py`, `catalog/views_public.py`,
`catalog/views_dashboard.py`, plus orders and platform user lists).

A client reading the schema picks `search`, gets an unfiltered list and no error.
That is worse than not offering search: it looks like it works. `q` and `search`
cannot both stay; the fix is to make `search` the one global contract (set
`search_fields` where it is wanted) or to drop `SearchFilter` and document `q`
explicitly. Dropping the filter and keeping `q` is the smaller, more honest
change, because `q` is already the documented name on those five operations.

## High

### H1 — Five operations where the schema and the code disagree

| Operation | Code does | Schema says | Cause |
|---|---|---|---|
| `POST /dashboard/products/{id}/images/` and siblings | 201 | 201 | ok |
| `POST /carts/` | needs `{store}`, answers 200 **or** 201 | no request body, only 201 | `@extend_schema` on `create()`, which drf-spectacular skips |
| `PATCH /carts/{id}/items/{item_pk}/` | 200, or 204 when quantity hits 0 | 200 only | 204 branch undocumented |
| `DELETE /dashboard/products/{id}/` | 200 + archived product body | 204 | verb-inferred response |
| `PATCH /courier/availability/` | applies `is_available` only | accepts `vehicle`, `plate`, `is_active` | serializer reused from a wider update |
| `PATCH /platform/users/{id}/` | applies `is_active`, `full_name` | `is_active` is read-only in the component | serializer read-only flag |

`POST /carts/` is the first call in the customer flow. A generated client types
it as no-body and then gets a 400 for a missing `store`. The cart item and
product delete cases make a client treat success as a parse error. The two
serializer cases make a client send fields that are silently dropped — the
worst failure mode, because it looks like it worked.

The durable fix is a *runtime* contract test that walks the generated schema and
asserts the response status each operation actually returns, not just that
`schema.yml` matches the generator. The existing drift test in
`tests/test_docs.py` compares file to generator, so it cannot catch a generator
that is wrong about the code.

### H2 — Errors are prose, so clients cannot branch on them

Errors look like `{"detail": "That job belongs to another company."}` or a field
array. `core/exceptions.py` already gives `Conflict`, `BusinessRuleViolation` and
`InvalidTransition` a `default_code`, but DRF only emits `code` inside
`ValidationError` details — the rendered body for an `APIException` is
`{"detail": ...}` and the code is lost.

A client that wants to show "this order was already cancelled" has to substring-
match English. Every non-English client, every copy change and every reworded
message is a breaking change. This is the classic inconsistent-error-format
problem, and it is cheap to fix now: one `EXCEPTION_HANDLER` that renders
`{"detail": ..., "code": ...}` for object-level errors, keeps DRF's field arrays
for validation, and documents the known codes as an enum in the schema.

Codes should be stable and low-cardinality (`conflict`, `invalid_transition`,
`business_rule`, `not_found`, `throttled`, `permission_denied`), not one per
message.

## Medium

### M1 — List payloads over-fetch and carry PII

`ProductPublicSerializer` ships `description` on every browse row, when the
catalog page needs it only on detail. Order briefs
(`OrderSummarySerializer`) carry a `customer` object with name, email and phone
to the store dashboard and, in `OrderDeliverySerializer`, to the courier. A
courier needs the phone of the customer on the job; a store does not need the
email. `delivery/serializers.py:235` (`JobOrderSerializer`) exposes the whole
address snapshot to the courier, which is fine, but the same shape reaches
surfaces that only need a name.

List versus detail serializers, and a `CustomerBrief` that carries only what
each surface needs, is the fix. It changes response shapes, so it must land
before the clients are generated.

### M2 — Public store browse loads every active store per request

`_visible_stores()` then a Python `haversine_km` loop
(`stores/views_public.py:61-70`). With 50 stores it is invisible; with 5,000 it
is a full table scan per anonymous request, and pagination happens after the
scan so `page_size` does not bound the work. Moving `q` and `is_open` into SQL
(part of C2) removes most of it; the radius needs a bounding box first
(`lat BETWEEN ... AND ...`, `lng BETWEEN ...`) and haversine only on the
survivors.

### M3 — No cache validators on the public catalog

`/stores/`, `/stores/{slug}/`, `/stores/{slug}/categories/`,
`/stores/{slug}/products/` and `/stores/{slug}/products/{slug}/` are anonymous,
cacheable and change slowly. They send no `ETag` and no `Cache-Control`, so
every visit is a full round trip. `ConditionalGetMiddleware` plus
`@cache_page`/`Cache-Control: public, max-age=60` on the list views is enough;
the detail views get a short max-age with `stale-while-revalidate`. Nothing
private may be cached.

## Low

### L1 — Naming drift, free only while `apps/` is empty

- `/api/v1/company/company/` doubles a segment. Should be `/company/profile/`.
- URL confs say `{pk}` and `{item_pk}`; the schema prints `{id}` and
  `{item_pk}`. One convention, `{id}`, everywhere except the cart item, where
  `{item_id}` is the honest name.
- `ws-ticket` is a `POST` for the courier and a `GET` for the customer, store and
  dispatcher. `GET` is correct — it reads a short-lived token and changes no
  state — so the courier route should move.
- `POST /auth/logout/` and `POST /password/change/` are fine; no change.

Every one of these is breaking, and every one is free today because no client has
generated types yet. They stop being free the day `apps/` has code.

### L2 — No correlation id

Nothing ties an error report to a log line. An `X-Request-ID` middleware that
reads an inbound header (or generates a UUID), stores it on the request, echoes
it in the response and includes it in the error body makes a support ticket
actionable. It must be exempt from `SECURE_SSL_REDIRECT` for `/healthz/` like
the rest.

## Work order

Cheapest-first inside each severity; testing at the end is deliberate, so each
commit is reviewable on its own diff.

### Critical

- [x] **C1** Scoped throttles: default anon/user rates, named scopes for login,
      register, password reset, checkout, quote; `429` + `Retry-After`; relaxed
      rates in `config/settings/test.py`.
- [x] **C2** `PublicStoreListView` returns a queryset: `q`, `is_open` and
      `ordering` in SQL, radius bounded then haversine; `?ordering=` no longer
      500s.
- [x] **C3** One search contract: remove the global `SearchFilter` and the dead
      `search` parameter from all 34 operations, keep `q` where it works.

### High

- [x] **H1** Fix all five drifts: `@extend_schema` on `post()` for `POST /carts/`;
      document the 204 branch of the cart item PATCH; product `DELETE` returns
      `200` with a body (documented); courier availability takes only
      `is_available`; platform user PATCH gets its own serializer.
- [ ] **H2** Stable error codes: one `EXCEPTION_HANDLER`, `code` on object-level
      errors, field arrays untouched, codes documented in the schema.

### Medium

- [ ] **M1** List-versus-detail serializers and a per-surface customer brief;
      no email/phone where the surface does not need it.
- [x] **M2** Store radius filtering: the haversine is an SQL annotation
      (`core.geo.distance_km_expression`), so the filter and the page slice
      both happen in Postgres — closed by C2, no bounding box needed.
- [ ] **M3** `ETag` + `Cache-Control` on the five public catalog reads.

### Low

- [ ] **L1** `/company/company/` → `/company/profile/`; `{item_pk}` →
      `{item_id}`; courier `ws-ticket` `POST` → `GET`.
- [ ] **L2** `X-Request-ID` middleware, echoed and logged, present in error
      bodies.

### Verification

- [ ] `pytest` green, `ruff check .` and `ruff format --check .` clean.
- [ ] `python manage.py spectacular --file schema.yml` regenerated and committed.
- [ ] `/api/docs/` renders the new operations; `config/api_text.py` has an entry
      for every one.

### Follow-ups outside this pass

- **Per-email login lockout.** C1 throttles by IP; distributed credential
  stuffing rotates IPs. A cache-backed failure counter keyed by email, checked
  before the password is verified, closes that gap.
- **Cursor pagination** for order and notification history, where offset paging
  drifts as rows are inserted.
