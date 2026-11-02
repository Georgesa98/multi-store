# Multi-Store Marketplace + Delivery — Django Backend

This repo is the **Django + DRF backend only** for a multi-store marketplace with
per-store cash-on-delivery fulfilment. Customers and couriers use a Flutter app;
store admins and super admins use a custom React web dashboard (not in this repo).

## 1. Product rules

- A customer can hold carts from several stores at once and check out all of them in one action.
- Checkout produces **one `CheckoutGroup`** and **one `Order` per store**. Orders are independent afterwards.
- Payment is **cash on delivery (COD)**, collected per order by that store's own courier.
- Couriers are **store employees**, not a shared pool.
- Currency is **SYP**, fixed for now, carried on each order.
- Live map tracking of the courier is in scope (WebSocket).

## 2. Stack

Python 3.12+, Django 5.x, DRF, SimpleJWT, drf-spectacular, django-filter, channels +
channels-redis, Celery + Redis, Postgres 16, Pillow, django-environ, psycopg[binary].

> This checkout runs **Python 3.14 + Django 6.0** (see Decisions). Postgres and
> Redis run in WSL; the Django process runs on Windows. The WSL Postgres listens on
> **port 5433** because a native Windows cluster (Odoo) owns 5432.

```bash
# once
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env          # fill DATABASE_URL / REDIS_URL

# every day
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
celery -A config worker -l info
celery -A config beat -l info
```

Testing: `pytest` (pytest-django), `ruff check .` + `ruff format .`. Every endpoint
gets at least a happy-path test plus a tenancy test.

## 3. Layout

```
config/            settings/{base,dev,prod}.py, urls.py, asgi.py, celery.py
core/              TimeStampedModel, StoreScopedModel, managers, permissions, pagination, enums
accounts/          User, Address, CustomerProfile, CourierProfile, DeviceToken
stores/            Store, StoreMembership, OpeningHours, DeliveryZone
catalog/           Category, Product, ProductImage, ProductVariant, InventoryMovement
cart/              Cart, CartItem
orders/            CheckoutGroup, Order, OrderItem, OrderStatusEvent, OrderSequence, Coupon, CouponRedemption
delivery/          Delivery, DeliveryEvent, CourierLocation, DeliveryLocationPing
reviews/           Review
notifications/     Notification
analytics/         DailyStoreStat, DailyProductStat, LedgerEntry
api/v1/            URL confs per surface: auth, public, dashboard, courier, platform
```

Create apps in that order and migrate each one as you finish it. Do not squash into
one initial migration.

## 4. Non-negotiable rules

1. `AUTH_USER_MODEL = "accounts.User"` is set **before the first `migrate`**. Never change it later.
2. Django admin is **not** a product surface. Do not build features into it. `/admin/` is mounted in DEBUG only; super-admin capability is exposed through `/api/v1/platform/`.
3. Every store-owned queryset goes through `for_user()` / an explicit store filter. A store admin requesting another store's object gets **404, never 403** (no existence leak).
4. Business logic lives in `services.py` per app, not in views or serializers. Views: validate → call service → serialize.
5. All money is `Decimal`, never `float`. Totals are computed server-side only. Client-supplied prices/totals are ignored.
6. `OrderItem` fields ending in `_snapshot` are written once at creation and never updated. No UPDATE path may exist for them.
7. Order status changes only through `orders.services.transition()`, which validates the transition table and writes an `OrderStatusEvent`.
8. Any stock mutation goes through `InventoryMovement` (append-only) inside the same transaction as the change.
9. Multi-object writes are wrapped in `transaction.atomic()`. Stock decrements use `select_for_update()`.
10. No model is deleted hard if it appears on an order. Use `status`, `is_active`, or `archived`.

## 5. Enums

`core/enums.py` holds all of them: `Role`, `StoreStatus`, `MemberRole`,
`ProductStatus`, `OrderStatus`, `PaymentStatus`, `DeliveryStatus`,
`InventoryReason`, `CouponType`, `LedgerKind`, `NotificationType`, plus
`DevicePlatform` and `Vehicle`.

```
Role           = super_admin, store_admin, store_staff, courier, customer
StoreStatus    = pending, active, suspended, closed
MemberRole     = owner, manager, staff
ProductStatus  = draft, active, archived
OrderStatus    = pending, confirmed, preparing, ready, assigned,
                 out_for_delivery, delivered, cancelled, refunded
PaymentStatus  = unpaid, collected, waived
DeliveryStatus = unassigned, offered, accepted, picked_up,
                 delivered, failed, cancelled
InventoryReason= restock, sale, cancel_return, manual, damage
CouponType     = percent, fixed
LedgerKind     = sale, refund, commission, payout
NotificationType = order_update, assignment, payment, system
```

## 6. Data model

Field lists are authoritative. Add nothing to a model without a reason recorded here.

### core

```python
class TimeStampedModel(models.Model):  # abstract; also gives a UUID pk
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)


class StoreScopedQuerySet(models.QuerySet):
    def for_user(self, user):
        if user.role == Role.SUPER_ADMIN:
            return self
        store_id = resolve_store_id(user)  # NOT user.store_id — see Decisions
        return self.filter(store_id=store_id) if store_id else self.none()


class StoreScopedModel(TimeStampedModel):  # abstract; store FK + objects = StoreScopedManager()
    store = FK("stores.Store", on_delete=CASCADE, db_index=True)
```

### accounts

- `User(pk=UUID)` — `email` unique + `USERNAME_FIELD`, `full_name`, `phone`, `role`, `is_active`, `is_staff`, `date_joined`, `last_login`. *(Phase 0)*
- `Address(customer→User)` — `label`, `line1`, `line2`, `city`, `notes`, `lat`, `lng` (`Decimal(9,6)`), `is_default`. DB constraint: at most one default per customer. *(Phase 0)*
- `CustomerProfile(1:1 User)` — `default_address` (nullable FK, SET_NULL). *(Phase 0)*
- `CourierProfile(1:1 User)` — `store` FK **non-null**, `vehicle` enum, `plate`, `is_available`, `avg_rating` `Decimal(3,2)`, `deliveries_count`. *(Phase 1 — needs `stores.Store`)*
- `DeviceToken` — `user`, `token` unique, `platform`, `is_active`. *(Phase 0)*

Couriers do **not** get a `StoreMembership`. `CourierProfile.store` is the only source of truth.

### stores

- `Store(pk=UUID)` — `owner→User`, `slug` unique, `code` unique (order-number prefix), `name`, `description`, `phone`, `address_text`, `status`, `logo`, `cover`, `lat`, `lng`, `currency` (default `SYP`), `commission_rate` `Decimal(5,4)`, `is_accepting_orders`.
- `StoreMembership` — `store`, `user`, `role`, `is_active`; unique `(store, user)`. v1: one active store per store admin, enforced in the service.
- `OpeningHours` — `store`, `weekday` 0–6, `open_time`, `close_time`, `is_closed`; unique `(store, weekday)`.
- `DeliveryZone` — `store`, `name`, `center_lat`, `center_lng`, `radius_km`, `fee`, `min_order_total`, `eta_minutes`, `is_active`.

Zones are radius-based. **No PostGIS.** Haversine helper in `core/geo.py`.

### catalog

- `Category` — `store` **nullable** (null = platform-wide), `parent`, `name`, `slug`, `sort_order`, `is_active`; unique `(store, slug)`.
- `Product` (StoreScoped) — `category`, `name`, `slug`, `description`, `status`, `is_available`, `avg_rating`, `rating_count`, `sold_count`; unique `(store, slug)`; index `(store, status)`.
- `ProductImage` — `product`, `image`, `sort_order`, `alt`.
- `ProductVariant` — `product`, `sku` unique, `label` (default `"Default"`), `price`, `compare_at_price`, `stock_qty`, `is_active`; unique `(product, label)`.
- `InventoryMovement` — `variant`, `delta`, `reason`, `order` (nullable), `created_by`, `note`; index `(variant, created_at)`.

Stock lives **only** on `ProductVariant`. Simple products get one auto-created variant labelled `Default`.

### cart

- `Cart` — `customer`, `store`, `coupon` (nullable FK); unique `(customer, store)`.
- `CartItem` — `cart`, `variant`, `quantity`; unique `(cart, variant)`.

### orders

- `CheckoutGroup(pk=UUID)` — `customer`, `address_snapshot` JSON, `idempotency_key` unique nullable, `notes`.
- `Order(pk=UUID, StoreScoped)` — `group`, `customer`, `number` (`PIZ-000118`), `status`, `payment_method` (default `cod`), `payment_status`, `subtotal`, `delivery_fee`, `discount_total`, `tax_total`, `total`, `currency`, `address_snapshot` JSON, `customer_note`, `cancelled_at`, `cancel_reason`, `delivered_at`.
  - unique `(store, number)`, check `total >= 0`, indexes `(store,status)`, `(store,created_at)`, `(customer,created_at)`.
- `OrderItem` — `order`, `product` (SET_NULL), `variant` (SET_NULL), `name_snapshot`, `variant_label_snapshot`, `image_url_snapshot`, `unit_price`, `quantity`, `line_total`, `options_snapshot` JSON.
- `OrderStatusEvent` — `order`, `from_status`, `to_status`, `actor` (SET_NULL), `actor_role`, `note`; index `(order, created_at)`.
- `OrderSequence` — `store` 1:1, `last_number`. Incremented with `select_for_update()` to allocate `Order.number`.
- `Coupon` — `store` nullable, `code`, `discount_type`, `value`, `min_order_total`, `max_discount`, `starts_at`, `ends_at`, `max_uses`, `used_count`, `is_active`; conditional unique `(store, code)` for store coupons and `code` for `store IS NULL`.
- `CouponRedemption` — `coupon`, `customer`, `order`, `discount_amount`; unique `(coupon, order)`.

Invariants to test:

- `total == subtotal + delivery_fee + tax_total - discount_total` and `>= 0`.
- `sum(item.line_total) == subtotal`.
- `line_total == unit_price * quantity`.
- Snapshot fields unchanged after product rename/reprice.

### delivery

- `Delivery(StoreScoped)` — `order` 1:1, `courier` (SET_NULL), `zone` (SET_NULL), `status`, `assign_attempts`, `offered_at`, `accepted_at`, `picked_up_at`, `delivered_at`, `failed_at`, `distance_km`, `fee`, `cash_to_collect`, `cash_collected`, `cash_collected_at`, `proof_photo`, `proof_otp`, `proof_note`, `failure_reason`.
  - indexes `(store,status)`, `(courier,status)`, `(status,offered_at)`.
- `DeliveryEvent` — `delivery`, `from_courier`, `to_courier`, `action`, `actor`.
- `CourierLocation` — 1:1 `courier`; `lat`, `lng`, `accuracy_m`, `heading`, `is_online`. Latest position only.
- `DeliveryLocationPing` — `delivery`, `lat`, `lng`; index `(delivery, created_at)`. Sampled trail (max 1 per 60 s).

### reviews / notifications / analytics

- `Review` — 1:1 `order_item`, `customer`, `store`, `product` (SET_NULL), `rating` 1–5, `comment`, `store_reply`, `replied_at`.
- `Notification` — `user`, `type`, `title`, `body`, `data` JSON, `read_at`; index `(user, read_at)`.
- `DailyStoreStat` — `store`, `date`, `orders_placed`, `orders_delivered`, `orders_cancelled`, `new_customers`, `gross_sales`, `net_sales`, `delivery_fees`, `discounts`, `refunds`; unique `(store, date)`.
- `DailyProductStat` — `store`, `product`, `date`, `qty_sold`, `revenue`; unique `(store, product, date)`.
- `LedgerEntry` — `store`, `order` nullable, `delivery` nullable, `kind`, `gross`, `commission`, `net`. **Append-only**; corrections are compensating rows.

## 7. Order state machine

```
pending ─→ confirmed ─→ preparing ─→ ready ─→ assigned ─→ out_for_delivery ─→ delivered
   │           │            │           │
   └───────────┴────────────┴───────────┴──→ cancelled
any non-terminal ─→ refunded        (super_admin only)
```

| from | to | allowed actors |
|---|---|---|
| pending | confirmed, cancelled | store_admin, customer, super_admin |
| confirmed | preparing, cancelled | store_admin, super_admin |
| preparing | ready, cancelled | store_admin |
| ready | assigned, cancelled | store_admin |
| assigned | out_for_delivery, ready (reassign) | courier, store_admin |
| out_for_delivery | delivered, cancelled | courier, super_admin |
| any non-terminal | cancelled | super_admin |
| any non-terminal | refunded | super_admin |

Entering `assigned` requires a `Delivery` with a courier. `delivered` sets
`payment_status=collected` and writes `cash_collected`. `cancelled` restores stock via
`InventoryMovement(reason=cancel_return)`. Illegal transitions raise `InvalidTransition`
→ HTTP 409.

## 8. API conventions

- Base `/api/v1/`. OpenAPI at `/api/schema/`, Swagger at `/api/docs/`.
- Auth: JWT (SimpleJWT). `access` 15 min, `refresh` 7 days, rotation + blacklist. Header `Authorization: Bearer`.
- Every list endpoint: `?page=&page_size=` (default 20, max 100) → `{count, next, previous, results}`.
- Filters via django-filter query params, documented in the schema.
- IDs are UUID strings. Timestamps ISO-8601 UTC.
- **Money is serialized as a string** (`"125000.00"`) — `COERCE_DECIMAL_TO_STRING=True`.
- Errors: `{"detail": "..."}` for object-level, `{"field": ["..."]}` for validation. `409` illegal transition, `422` business rule (min order, zone, stock), `400` malformed.
- Cross-tenant access → `404`.
- Write actions that change state are **POST to a named endpoint**, never `PATCH status`.
- `POST /api/v1/checkout/` requires header `Idempotency-Key`; same key returns the original `CheckoutGroup`.
- Permissions are declared per view class. There is no endpoint without an explicit permission class.

## 9. Endpoints

### 9.1 Auth / account — `/api/v1/auth/` *(Phase 0, done)*

| Method | Path | Notes |
|---|---|---|
| POST | `register/` | customer signup |
| POST | `login/` | email+password → access, refresh, role, profile |
| POST | `refresh/` | rotates |
| POST | `logout/` | blacklists refresh |
| GET/PATCH | `me/` | profile of current user |
| POST | `password/change/` | |
| POST | `password/reset/` | |
| POST | `password/reset/confirm/` | |
| GET/POST | `device-tokens/` | register push token |
| DELETE | `device-tokens/{id}/` | |

### 9.2 Customer — `/api/v1/`

| Method | Path | Notes |
|---|---|---|
| GET/POST | `addresses/` | |
| GET/PATCH/DELETE | `addresses/{id}/` | |
| POST | `addresses/{id}/set-default/` | |
| GET | `stores/` | browse: `q`, `lat,lng,radius`, `is_open`, ordering |
| GET | `stores/{slug}/` | detail + hours + zones summary |
| GET | `stores/{slug}/categories/` | |
| GET | `stores/{slug}/products/` | `category`, `q`, `min_price`, `max_price`, `in_stock` |
| GET | `stores/{slug}/products/{slug}/` | |
| POST | `stores/{slug}/delivery-quote/` | `{lat,lng}` → zone, fee, min_order, eta |
| GET | `carts/` | all active carts grouped by store |
| POST | `carts/` | `{store}` → get-or-create |
| POST | `carts/{id}/items/` | `{variant, quantity}` |
| PATCH/DELETE | `carts/{id}/items/{item}/` | |
| POST | `carts/{id}/coupon/` | `{code}` |
| DELETE | `carts/{id}/coupon/` | |
| POST | `carts/{id}/clear/` | |
| GET | `checkout/preview/` | per-store subtotal/fee/discount/total + problems |
| POST | `checkout/` | `Idempotency-Key`; `{address_id, store_ids[], notes}` |
| GET | `checkout-groups/` | history |
| GET | `checkout-groups/{id}/` | with nested orders |
| GET | `orders/` | `status`, `store`, `from`, `to` |
| GET | `orders/{id}/` | |
| GET | `orders/{id}/timeline/` | status events |
| POST | `orders/{id}/cancel/` | allowed only while `pending`/`confirmed` |
| POST | `order-items/{id}/review/` | `{rating, comment}`; requires `delivered` |
| GET/POST | `notifications/` | |
| POST | `notifications/{id}/read/`, `notifications/read-all/` | |

### 9.3 Store dashboard — `/api/v1/dashboard/`

| Method | Path | Notes |
|---|---|---|
| GET/PATCH | `store/` | own store only |
| GET/PUT | `opening-hours/` | bulk replace |
| GET/POST | `zones/`, `zones/{id}/` | |
| GET/POST | `categories/`, `categories/{id}/` | |
| GET/POST | `products/` | `?q&status&category` |
| GET/PATCH/DELETE | `products/{id}/` | delete = archive |
| POST | `products/{id}/images/` | multipart |
| POST | `products/{id}/variants/` | |
| PATCH | `variants/{id}/` | price, label, is_active |
| POST | `variants/{id}/stock/` | `{delta, reason, note}` → `InventoryMovement` |
| GET | `inventory-movements/` | audit log |
| GET | `orders/` | `status`, `from`, `to`, `q` |
| GET | `orders/{id}/` | |
| POST | `orders/{id}/confirm/`, `preparing/`, `ready/`, `cancel/` | state machine |
| GET | `couriers/` | |
| POST | `couriers/invite/` | `{email, full_name, phone}` |
| PATCH | `couriers/{id}/` | deactivate |
| GET | `deliveries/` | `status`, `courier` |
| POST | `deliveries/{id}/assign/` | `{courier_id}` |
| POST | `deliveries/{id}/reassign/` | `{courier_id}` |
| GET | `insights/summary/` | `?from&to` totals + AOV |
| GET | `insights/revenue/` | daily series |
| GET | `insights/top-products/` | |
| GET | `insights/orders-by-status/` | |
| GET | `insights/delivery-performance/` | avg minutes, failure rate |
| GET/POST | `coupons/`, `coupons/{id}/` | |
| GET | `reviews/` | |
| POST | `reviews/{id}/reply/` | |
| GET | `ledger/` | own entries |

### 9.4 Courier — `/api/v1/courier/`

| Method | Path | Notes |
|---|---|---|
| GET | `me/` | profile + today's stats |
| PATCH | `availability/` | `{is_available}` |
| GET | `offers/` | pending offers |
| POST | `deliveries/{id}/accept/` | |
| POST | `deliveries/{id}/decline/` | reassigns |
| GET | `deliveries/` | `?active=true` |
| GET | `deliveries/{id}/` | includes pickup/drop coords + items |
| POST | `deliveries/{id}/pickup/` | |
| PATCH | `deliveries/{id}/location/` | `{lat,lng,accuracy_m,heading}`; broadcast |
| POST | `deliveries/{id}/deliver/` | `{otp?, proof_photo?}` |
| POST | `deliveries/{id}/fail/` | `{reason}` |
| POST | `deliveries/{id}/ws-ticket/` | 60 s JWT for socket auth |
| GET | `earnings/` | COD collected summary |

### 9.5 Platform (super admin) — `/api/v1/platform/`

| Method | Path | Notes |
|---|---|---|
| GET | `stores/` | all, filter by status |
| GET | `stores/{id}/` | full detail |
| POST | `stores/{id}/approve/` | pending → active |
| POST | `stores/{id}/suspend/` | `{reason}` |
| GET/POST | `stores/` onboarding | super admin creates store + invites owner |
| GET | `users/` | `role`, `q` |
| PATCH | `users/{id}/` | activate/deactivate |
| GET | `orders/` | every store |
| GET | `deliveries/` | |
| GET | `insights/overview/` | GMV, orders, active stores |
| GET | `insights/revenue/` | platform series |
| GET | `ledger/` | |
| GET | `payouts/` | per-store owed vs paid |
| POST | `payouts/{id}/mark-paid/` | |
| GET/POST | `coupons/` | platform-wide coupons |

### 9.6 WebSocket

`wss://host/ws/delivery/{delivery_id}/?ticket=<60s-jwt>`

Server → client:

```json
{"type": "location", "lat": 33.51, "lng": 36.29, "at": "..."}
{"type": "status", "status": "picked_up", "at": "..."}
{"type": "eta", "minutes": 12}
```

Ticket issuance is `POST /api/v1/courier/deliveries/{id}/ws-ticket/` for couriers;
customers get theirs from `GET /api/v1/orders/{id}/ws-ticket/` (see Open questions).
`TrackingConsumer` is read-only for both; location arrives over HTTP so a dropped
socket never loses data.

## 10. Permission matrix

| Surface | Who | Scoping |
|---|---|---|
| `/auth/`, `/addresses/`, `/carts/`, `/checkout/`, `/orders/` | customer | own rows only |
| `/courier/` | courier | own profile, deliveries with `courier=me` |
| `/dashboard/` | store_admin, store_staff | `store=request.store` |
| `/dashboard/` write ops | store_admin, manager | staff is read-only |
| `/platform/` | super_admin | all |
| `/ws/delivery/{id}/` | courier on it, order's customer, store's admins | ticket + object check |

`request.store` is resolved from `StoreMembership`; if a store admin has none, every
dashboard call 403s.

## 11. Background jobs (Celery)

| Job | Schedule | Does |
|---|---|---|
| `expire_courier_offers` | every 30 s | `offered` older than 90 s → reassign, `DeliveryEvent(timeout)` |
| `cancel_stale_pending_orders` | every 5 min | `pending` older than 30 min → cancel, restore stock |
| `rollup_daily_stats` | 00:15 daily | yesterday into `DailyStoreStat`, `DailyProductStat` |
| `write_ledger_for_delivered` | on transition | `LedgerEntry(sale)` + commission |
| `send_order_notifications` | on transition | push + `Notification` |
| `prune_location_pings` | weekly | delete pings older than 30 days |

Insights endpoints read rollups for past days and live-query **today only**.

## 12. Testing requirements

- `tests/test_tenancy.py` — two stores, one fixture each; assert every dashboard/courier endpoint 404s cross-tenant. Write this before the dashboard API.
- `tests/test_checkout.py` — multi-store cart → one group + N orders; totals correct; idempotency replay returns the same group; concurrent checkout cannot oversell (two threads, one `select_for_update` winner).
- `tests/test_state_machine.py` — every allowed transition passes, every illegal one 409s, events written.
- `tests/test_snapshots.py` — rename/reprice product after ordering; `OrderItem` unchanged.
- `tests/test_delivery.py` — assign → accept → pickup → deliver; offer expiry reassigns; COD amount recorded.
- `tests/test_money.py` — no float anywhere in serialized output.

## 13. Build order

1. **Phase 0** — settings split, custom user, JWT, spectacular, docker-compose, `seed_demo`, tenancy test skeleton.
2. **Phase 1** — stores + memberships + catalog + store dashboard CRUD + platform store approval.
3. **Phase 2** — cart, checkout with `Idempotency-Key`, order state machine, COD fields.
4. **Phase 3** — courier assignment, delivery flow, zones/fees, live tracking, notifications.
5. **Phase 4** — reviews, coupons, insights + rollups, ledger + payouts.

Each phase ends with `pytest` green, `ruff check` clean, and `/api/schema/` regenerated.

## 14. Never do

- Never `DELETE` a product, variant, store, or user that appears in an order.
- Never accept `price`, `total`, or `subtotal` from the request body.
- Never `PATCH` an order's status directly.
- Never query a store-owned model without a store filter.
- Never `float` money, never `round()` half-up by hand — use `Decimal` and `quantize(Decimal("0.01"))`.
- Never store derived values that a rollup can compute, except the documented denormalized counters (`avg_rating`, `rating_count`, `sold_count`, `deliveries_count`, `used_count`).
- Never build UI in Django templates or rely on `/admin/`.

## 15. Decisions and deviations

Recorded so they are not re-litigated by accident.

1. **Python 3.14 + Django 6.0** instead of "Python 3.12+, Django 5.x" — the only
   interpreter on the machine is 3.14; the user approved Django 6.
2. **Every model gets a UUID primary key.** Section 8 says all API ids are UUID
   strings, while Section 6 only marked four models as UUID. `TimeStampedModel`
   carries the pk so the rule holds everywhere.
3. **All enums live in `core/enums.py`.** Cross-app vocabulary without circular imports.
   `DevicePlatform` and `Vehicle` were added because the model lists don't enumerate
   their values.
4. **`StoreScopedQuerySet.for_user()` uses `core.tenancy.resolve_store_id(user)`**, not
   `user.store_id` (which does not exist). Resolution order: attached
   `active_store_id` → active `StoreMembership` → `CourierProfile.store`.
5. **`CourierProfile` moves to Phase 1** because its non-null `store` FK needs
   `stores.Store`; it ships as `accounts.0002` right after `stores.0001`.
6. **`django-cors-headers` added** to the stack; the React dashboard is a different
   origin and cannot talk to DRF without it.
7. **`/admin/` is mounted only when `DEBUG`**, and no features are built into it.
8. **`DeviceToken` listing is paginated** like every other list endpoint.
9. **Password reset endpoints are implemented in Phase 0** (console email in dev,
   `FRONTEND_URL` configurable), because they are pure account logic.
10. **Store-scoped FKs use `related_name="+"`** to keep the reverse API surface explicit
    rather than accidental.
11. **WSL Postgres was moved to port 5433.** A native Windows service
    (`PostgreSQL_For_Odoo`) already listens on 5432, so Windows could never reach the
    WSL cluster. Role `george` owns database `multistore` and has `CREATEDB` for the
    test database.
12. **`Store` gains `suspended_reason`.** `/platform/stores/{id}/suspend/` takes a
    reason and there was nowhere else to keep it before notifications exist.
13. **`InventoryMovement.order` is added in Phase 2.** The FK needs `orders.Order`,
    which does not exist yet; the field ships with the first orders migration.
14. **`request.store` is resolved in the permission classes, not middleware.** DRF
    authenticates the JWT per view, so a Django middleware only ever sees an
    `AnonymousUser`. `IsDashboardUser` attaches `request.membership` and
    `request.store`; `IsDashboardWriter` adds the owner/manager check.
15. **`Store.code` supplies the order-number prefix.** A unique short code (max 8)
    set at onboarding (derived from the name when omitted); `Order.number` is
    `{code}-{sequence:06d}` from the per-store `OrderSequence`.
16. **`Cart.coupon` is a nullable FK to `orders.Coupon`.** Applied and validated on
    `POST carts/{id}/coupon/`, then re-validated at checkout; the checkout path is
    the only place a `CouponRedemption` and `used_count` change happen.
17. **`CheckoutGroup.idempotency_key` is globally unique.** A replay returns the
    original group only to the same customer; another customer reusing the key
    gets 409 rather than someone else's group.
18. **`refunded` keeps stock and payment status.** COD cash was already collected
    and the goods delivered, so only the status changes; the compensating
    `LedgerEntry(kind=refund)` arrives with the ledger in Phase 4.
19. **Customers may cancel `pending` or `confirmed` orders.** §9.2 states that
    window, while §7's actor table omits the customer for `confirmed→cancelled`;
    the table is extended to match §9.2.
20. **Platform-wide coupon uniqueness uses a partial unique constraint.** Postgres
    treats NULLs as distinct, so `code` is unique where `store IS NULL` and
    `(store, code)` is unique where `store IS NOT NULL`.

## 16. Open questions (decide before the phase that needs them)

- **`Payout` model is missing**, yet `/platform/payouts/` and `mark-paid` exist.
- **`GET /orders/{id}/ws-ticket/`** is specified in 9.6 but absent from the 9.2 table.
