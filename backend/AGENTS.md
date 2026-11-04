# Multi-Store Marketplace + Delivery — Django Backend

This is the **Django + DRF backend** of the repository: a multi-store marketplace
with per-store cash-on-delivery fulfilment. It lives in `backend/`; the React
dashboard and the Flutter apps live in `apps/` and are owned by other developers
(see the repository root `AGENTS.md`). Every command below runs from `backend/`.

## 1. Product rules

- A customer can hold carts from several stores at once and check out all of them in one action.
- Checkout produces **one `CheckoutGroup`** and **one `Order` per store**. Orders are independent afterwards.
- Payment is **cash on delivery (COD)**, collected per order by the delivery company's courier.
- Couriers are **employees of a third-party delivery company**, never shared across companies.
- Delivery companies onboard through the platform (pending → active → suspended), exactly like stores.
- A delivery company publishes its own **zones** (coverage radius, fee, minimum order, ETA); a store no longer defines zones or sets the delivery fee.
- A store contracts one or more companies, ordered by **priority**. The first contracted company that covers the address quotes the fee; a later partner is the fallback.
- Stores only choose and contract companies; they never create, assign, or manage a courier.
- COD cash is held by the delivery company, which settles the store (settlement model arrives in Phase 4).
- Currency is **SYP**, fixed for now, carried on each order.
- Live map tracking of the courier is in scope (WebSocket).

## 2. Stack

Python 3.12+, Django 5.x, DRF, SimpleJWT, drf-spectacular, django-filter, channels +
channels-redis + daphne, Celery + Redis, Postgres 16, Pillow, django-environ,
psycopg[binary].

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
templates/         api/docs.html — the gated Scalar reference page
static/            vendor/scalar-*.js — the pinned viewer bundle
core/              TimeStampedModel, StoreScopedModel, managers, permissions, pagination, enums
accounts/          User, Address, CustomerProfile, CourierProfile, DeviceToken
stores/            Store, StoreMembership, OpeningHours
catalog/           Category, Product, ProductImage, ProductVariant, InventoryMovement
cart/              Cart, CartItem
orders/            CheckoutGroup, Order, OrderItem, OrderStatusEvent, OrderSequence, Coupon, CouponRedemption
delivery/          DeliveryCompany, CompanyMembership, StoreDeliveryPartner, DeliveryZone,
                   Delivery, DeliveryEvent, CourierLocation, DeliveryLocationPing
reviews/           Review
notifications/     Notification
analytics/         DailyStoreStat, DailyProductStat, LedgerEntry, Payout
api/v1/            URL confs per surface: auth, public, dashboard, company, courier, platform
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

`core/enums.py` holds all of them: `Role`, `StoreStatus`, `CompanyStatus`, `MemberRole`,
`ProductStatus`, `OrderStatus`, `PaymentStatus`, `DeliveryStatus`, `DeliveryAction`,
`InventoryReason`, `CouponType`, `LedgerKind`, `NotificationType`, plus
`DevicePlatform` and `Vehicle`.

```
Role           = super_admin, store_admin, store_staff, delivery_admin,
                 delivery_staff, courier, customer
StoreStatus    = pending, active, suspended, closed
CompanyStatus  = pending, active, suspended, closed
MemberRole     = owner, manager, staff
ProductStatus  = draft, active, archived
OrderStatus    = pending, confirmed, preparing, ready, assigned,
                 out_for_delivery, delivered, cancelled, refunded
PaymentStatus  = unpaid, collected, waived
DeliveryStatus = unassigned, requested, offered, accepted, picked_up,
                 delivered, failed, cancelled
DeliveryAction = requested, assigned, reassigned, released, accepted,
                 declined, picked_up, delivered, failed, cancelled
InventoryReason= restock, sale, cancel_return, manual, damage
CouponType     = percent, fixed
LedgerKind     = sale, refund, commission, payout
PayoutStatus   = pending, settled, paid
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
- `CourierProfile(1:1 User)` — `company` FK **non-null** (`delivery.DeliveryCompany`, PROTECT), `vehicle` enum, `plate`, `is_available`, `avg_rating` `Decimal(3,2)`, `deliveries_count`. *(Phase 3)*
- `DeviceToken` — `user`, `token` unique, `platform`, `is_active`. *(Phase 0)*

Couriers do **not** get a `StoreMembership` or a `CompanyMembership`.
`CourierProfile.company` is the only source of truth for who they work for.

### stores

- `Store(pk=UUID)` — `owner→User`, `slug` unique, `code` unique (order-number prefix), `name`, `description`, `phone`, `address_text`, `status`, `logo`, `cover`, `lat`, `lng`, `currency` (default `SYP`), `commission_rate` `Decimal(5,4)`, `is_accepting_orders`, `suspended_reason`.
- `StoreMembership` — `store`, `user`, `role`, `is_active`; unique `(store, user)`. v1: one active store per store admin, enforced in the service.
- `OpeningHours` — `store`, `weekday` 0–6, `open_time`, `close_time`, `is_closed`; unique `(store, weekday)`.

Stores no longer own `DeliveryZone`: zones belong to a delivery company (see below).
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

A delivery company is a standalone business, not part of a store. It has its own
team, its own coverage and its own riders.

- `DeliveryCompany(pk=UUID)` — `owner→User`, `slug` unique, `name`, `description`, `phone`, `address_text`, `status` (`CompanyStatus`), `logo`, `cover`, `lat`, `lng`, `commission_rate` `Decimal(5,4)` (platform's cut of fees), `is_accepting_jobs`, `suspended_reason`.
  - indexes `(status, is_accepting_jobs)`, `(slug)`; check `0 <= commission_rate <= 1`.
- `CompanyMembership` — `company`, `user`, `role` (`MemberRole`), `is_active`; unique `(company, user)`. v1: one active company per admin, enforced in the service.
- `StoreDeliveryPartner` — `store`, `company`, `priority` (lower first), `is_active`; unique `(store, company)`. The store's contract with a company; the quote walks these in priority order.
- `DeliveryZone` — `company`, `name`, `center_lat`, `center_lng`, `radius_km`, `fee`, `min_order_total`, `eta_minutes`, `is_active`; unique `(company, name)`.
- `Delivery(StoreScoped)` — `order` 1:1, `company` (PROTECT, nullable), `courier` (SET_NULL), `zone` (SET_NULL), `status`, `assign_attempts`, `requested_at`, `offered_at`, `accepted_at`, `picked_up_at`, `delivered_at`, `failed_at`, `distance_km`, `fee`, `cash_to_collect`, `cash_collected`, `cash_collected_at`, `proof_photo`, `proof_otp`, `proof_note`, `failure_reason`.
  - indexes `(store,status)`, `(company,status)`, `(courier,status)`, `(status,offered_at)`.
  - Created at checkout with the quoted `company`, `zone` and `fee` locked in; `cash_to_collect = order.total`.
- `DeliveryEvent` — `delivery`, `from_courier`, `to_courier`, `from_company`, `to_company`, `action` (`DeliveryAction`), `actor`, `note`; index `(delivery, created_at)`.
- `CourierLocation` — 1:1 `courier`; `lat`, `lng`, `accuracy_m`, `heading`, `is_online`. Latest position only.
- `DeliveryLocationPing` — `delivery`, `lat`, `lng`; index `(delivery, created_at)`. Sampled trail (max 1 per 60 s).

### reviews / notifications / analytics

- `Review` — 1:1 `order_item`, `customer`, `store`, `product` (SET_NULL), `rating` 1–5, `comment`, `store_reply`, `replied_at`.
- `Notification` — `user`, `type`, `title`, `body`, `data` JSON, `read_at`; index `(user, read_at)`.
- `DailyStoreStat` — `store`, `date`, `orders_placed`, `orders_delivered`, `orders_cancelled`, `new_customers`, `gross_sales`, `net_sales`, `delivery_fees`, `discounts`, `refunds`; unique `(store, date)`.
- `DailyProductStat` — `store`, `product`, `date`, `qty_sold`, `revenue`; unique `(store, product, date)`.
- `LedgerEntry` — `store`, `order` nullable, `delivery` nullable, `kind`, `gross`, `commission`, `net`. **Append-only**; corrections are compensating rows.
- `Payout` — `store`, `company` (PROTECT), `period_start`, `period_end` (a Mon–Sun week), `deliveries`, `cash_collected`, `delivery_fees`, `platform_commission`, `store_net`, `company_net`, `status` (`PayoutStatus`), `settled_at`, `paid_at`; unique `(store, company, period_start)`; index `(company, status)`, `(store, period_start)`. Materialised from the week's ledger, never rewritten once settled.

## 7. Order state machine

```
pending ─→ confirmed ─→ preparing ─→ ready ─→ assigned ─→ out_for_delivery ─→ delivered
   │           │            │           │
   └───────────┴────────────┴───────────┴──→ cancelled
any non-terminal or delivered ─→ refunded   (super_admin only)
```

| from | to | allowed actors |
|---|---|---|
| pending | confirmed, cancelled | store_admin, customer, super_admin |
| confirmed | preparing, cancelled | store_admin, super_admin |
| preparing | ready, cancelled | store_admin |
| ready | assigned, cancelled | store_admin, delivery_admin, courier, super_admin |
| assigned | out_for_delivery | courier, store_admin, delivery_admin |
| assigned | ready (release/reassign) | courier, store_admin, delivery_admin, super_admin |
| out_for_delivery | ready (failed attempt) | courier, store_admin, delivery_admin, super_admin |
| out_for_delivery | delivered, cancelled | courier, super_admin |
| any non-terminal | cancelled | super_admin |
| any non-terminal or delivered | refunded | super_admin |

Entering `assigned` requires a `Delivery` with a courier. `delivered` sets
`payment_status=collected` and writes `cash_collected`. `cancelled` restores stock via
`InventoryMovement(reason=cancel_return)` and cancels the `Delivery`.

`ready` asks the contracted company to take the job: the `Delivery` becomes
`requested` and lands in that company's offer pool. `fail` and `release` put the order
back to `ready` without re-offering it to the same company immediately
(`transition(..., request_delivery=False)`). Illegal transitions raise
`InvalidTransition` → HTTP 409.

## 8. API conventions

- Base `/api/v1/`. OpenAPI at `/api/schema/`, reference at `/api/docs/`,
  Swagger UI at `/api/docs/swagger/`, ReDoc at `/api/redoc/` — all four behind
  the `DOCS_AUTH_*` credential (see Decisions 38).
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
- Every operation carries a **summary and a description**, held in one table
  (`config/api_text.py`, decision 41). Adding an endpoint without an entry fails
  `tests/test_docs.py`.

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
| GET | `stores/{slug}/` | detail + hours + contracted `delivery_companies` |
| GET | `stores/{slug}/categories/` | |
| GET | `stores/{slug}/products/` | `category`, `q`, `min_price`, `max_price`, `in_stock` |
| GET | `stores/{slug}/products/{slug}/` | |
| GET | `stores/{slug}/reviews/` | public review wall |
| POST | `stores/{slug}/delivery-quote/` | `{lat,lng}` → company, zone, fee, min_order, eta |
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
| GET | `orders/{id}/ws-ticket/` | 60 s ticket for the tracking socket |
| POST | `orders/{id}/cancel/` | allowed only while `pending`/`confirmed` |
| POST | `order-items/{id}/review/` | `{rating, comment}`; requires `delivered` |
| GET/POST | `notifications/` | |
| POST | `notifications/{id}/read/`, `notifications/read-all/` | |

### 9.3 Store dashboard — `/api/v1/dashboard/`

| Method | Path | Notes |
|---|---|---|
| GET/PATCH | `store/` | own store only |
| GET/PUT | `opening-hours/` | bulk replace |
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
| GET | `companies/` | approved companies the store may contract |
| GET/POST | `partners/` | contracts; POST `{company_id, priority}` |
| PATCH/DELETE | `partners/{id}/` | priority / is_active; delete = deactivate |
| GET | `deliveries/` | own orders' deliveries: `status`, `company` |
| GET | `deliveries/{id}/` | |
| POST | `deliveries/{id}/request/` | `{company_id?}`; re-offer after a release |
| GET | `insights/summary/` | `?from&to` totals + AOV |
| GET | `insights/revenue/` | daily series |
| GET | `insights/top-products/` | |
| GET | `insights/orders-by-status/` | |
| GET | `insights/delivery-performance/` | avg minutes, failure rate |
| GET/POST | `coupons/`, `coupons/{id}/` | store coupons; delete = deactivate |
| GET | `reviews/` | own store only |
| POST | `reviews/{id}/reply/` | `{reply}`; stamps `replied_at` |
| GET | `ledger/` | own entries |

### 9.4 Delivery company — `/api/v1/company/`

The company's own dashboard: profile, team, riders, coverage and dispatch. Every
query is scoped to `request.company`; a foreign id is 404.

| Method | Path | Notes |
|---|---|---|
| GET/PATCH | `company/` | own company; status and commission are platform-run |
| GET | `members/` | team list |
| POST | `members/invite/` | `{email, full_name, phone?, role?}` |
| PATCH | `members/{id}/` | `{role?, is_active?}`; owner role is fixed |
| GET/POST | `couriers/` | list `?is_available&q`; POST hires a rider |
| PATCH | `couriers/{id}/` | vehicle, plate, availability, `is_active: false` |
| GET/POST | `zones/`, `zones/{id}/` | coverage, fee, min order, ETA |
| DELETE | `zones/{id}/` | retires the zone (`is_active=false`) |
| GET | `deliveries/` | `status`, `courier`, `active`: the company's job pool |
| GET | `deliveries/{id}/` | with items and events |
| POST | `deliveries/{id}/assign/` | `{courier_id}`; also accepts a requested job |
| POST | `deliveries/{id}/release/` | hands the job back; order returns to `ready` |
| POST | `deliveries/{id}/fail/` | `{reason}`; order returns to `ready` and is re-offered |
| GET | `earnings/` | `?from&to`: COD collected, gross fees, commission, net |

### 9.5 Courier — `/api/v1/courier/`

| Method | Path | Notes |
|---|---|---|
| GET | `me/` | profile + today's stats |
| PATCH | `availability/` | `{is_available}` |
| GET | `offers/` | requested jobs of the courier's own company |
| POST | `deliveries/{id}/accept/` | assigns to the accepting courier |
| POST | `deliveries/{id}/decline/` | `{note?}`; the job stays in the pool |
| GET | `deliveries/` | `?active=true`, own deliveries only |
| GET | `deliveries/{id}/` | includes pickup/drop coords + items |
| POST | `deliveries/{id}/pickup/` | |
| PATCH | `deliveries/{id}/location/` | `{lat,lng,accuracy_m,heading}` |
| POST | `deliveries/{id}/deliver/` | `{otp?, proof_photo?}`; records COD cash |
| POST | `deliveries/{id}/fail/` | `{reason}` |
| GET | `earnings/` | own COD collected summary |

### 9.6 Platform (super admin) — `/api/v1/platform/`

| Method | Path | Notes |
|---|---|---|
| GET/POST | `stores/` | list, filter by status; POST onboards store + owner |
| GET | `stores/{id}/` | full detail |
| POST | `stores/{id}/approve/` | pending → active |
| POST | `stores/{id}/suspend/` | `{reason}` |
| GET/POST | `companies/` | list, filter by status; POST onboards company + owner |
| GET | `companies/{id}/` | full detail |
| POST | `companies/{id}/approve/` | pending → active |
| POST | `companies/{id}/suspend/` | `{reason}`; stops accepting jobs |
| GET | `users/` | `role`, `q` |
| PATCH | `users/{id}/` | activate/deactivate |
| GET | `orders/` | every store |
| GET | `deliveries/` | every company: `status`, `company`, `store`, `from`, `to` |
| GET | `insights/overview/` | GMV, orders, active stores |
| GET | `insights/revenue/` | platform series |
| GET | `ledger/` | |
| GET | `payouts/` | weekly settlements; `store`, `company`, `status`, `from`, `to` |
| POST | `payouts/{id}/settle/` | `pending` → `settled`: the company handed the COD cash over |
| POST | `payouts/{id}/mark-paid/` | `settled` → `paid`; appends a `LedgerEntry(kind=payout)` |
| GET/POST | `coupons/` | platform-wide coupons |

### 9.7 WebSocket

`wss://host/ws/delivery/{delivery_id}/?ticket=<60s-jwt>`

Server → client:

```json
{"type": "location", "lat": 33.51, "lng": 36.29, "at": "..."}
{"type": "status", "status": "picked_up", "at": "..."}
{"type": "eta", "minutes": 12}
```

Ticket issuance is `POST /api/v1/courier/deliveries/{id}/ws-ticket/` for couriers,
`GET /api/v1/orders/{id}/ws-ticket/` for the order's customer,
`GET /api/v1/dashboard/orders/{id}/ws-ticket/` for the store and
`GET /api/v1/company/deliveries/{id}/ws-ticket/` for the dispatcher. The ticket is
a 60 s JWT naming one delivery, reusable within that minute so a reconnect needs no
extra HTTP call. `TrackingConsumer` is read-only for all of them; location arrives
over HTTP so a dropped socket never loses data. The `eta` frame is reserved for when
a live ETA exists; today only `location` and `status` are sent.

## 10. Permission matrix

| Surface | Who | Scoping |
|---|---|---|
| `/auth/`, `/addresses/`, `/carts/`, `/checkout/`, `/orders/` | customer | own rows only |
| `/courier/` | courier | own profile, deliveries with `courier=me`; offers from own company |
| `/company/` | delivery_admin, delivery_staff | `company=request.company` |
| `/company/` write ops | delivery_admin, manager | staff is read-only |
| `/dashboard/` | store_admin, store_staff | `store=request.store` |
| `/dashboard/` write ops | store_admin, manager | staff is read-only |
| `/platform/` | super_admin | all |
| `/ws/delivery/{id}/` | courier on it, order's customer, store's admins | ticket + object check |

`request.store` is resolved from `StoreMembership`; if a store admin has none, every
dashboard call 403s. `request.company` is resolved from `CompanyMembership` (or, for a
courier, `CourierProfile.company`); a company admin with none gets 403.

## 11. Background jobs (Celery)

| Job | Schedule | Does |
|---|---|---|
| `cancel_stale_pending_orders` | every 5 min | `pending` older than 30 min → cancel, restore stock |
| `rollup_daily_stats` | 00:15 daily | yesterday into `DailyStoreStat`, `DailyProductStat` |
| `write_ledger_for_delivered` | retry only | idempotent safety net for the synchronous ledger write |
| `materialise_payouts` | Monday 00:30 | roll the week that just ended into `Payout` rows |
| `send_order_notifications` | on transition | mirror the committed `Notification` rows to devices |
| `prune_location_pings` | weekly | delete pings older than 30 days |

The delivery offer pool has no per-courier expiry: a `requested` job stays in the
company's pool until a courier accepts, the dispatcher assigns, or the company
releases or fails it. Server-side offer timeouts and their Celery sweep return with
the tracking work in a later pass.

Insights endpoints read rollups for past days and live-query **today only**.

## 12. Testing requirements

- `tests/test_tenancy.py` — two stores, one fixture each; assert every dashboard/courier/company endpoint 404s cross-tenant. Write this before the dashboard API.
- `tests/test_checkout.py` — multi-store cart → one group + N orders; totals correct; idempotency replay returns the same group; concurrent checkout cannot oversell (two threads, one `select_for_update` winner).
- `tests/test_state_machine.py` — every allowed transition passes, every illegal one 409s, events written.
- `tests/test_snapshots.py` — rename/reprice product after ordering; `OrderItem` unchanged.
- `tests/test_companies.py` — platform onboarding/approval/suspension; zone and courier CRUD; cross-company 404.
- `tests/test_delivery.py` — checkout locks the quote; ready → requested; assign/accept → pickup → deliver; release and fail return the order to `ready`; COD amount recorded; earnings.
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
   `active_store_id` → active `StoreMembership`. A courier has no store.
5. **`CourierProfile` shipped in Phase 1** (`accounts.0002`), because its non-null
   `store` FK needed `stores.Store`. Phase 3 (`accounts.0003`) replaces that FK with
   `company` and backfills one company per store that had riders.
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
21. **Delivery companies are tenants in their own right.** A company has an owner,
    a `CompanyMembership` team and its own riders; it is onboarded, approved and
    suspended by the platform exactly like a store. A store never owns a courier.
22. **Zones move from `stores` to `delivery`.** `DeliveryZone.company` replaces
    `DeliveryZone.store` and the table ships in `delivery.0001`; `stores.0004`
    drops the old table. There was no production data, so nothing is copied.
    `DELETE zones/{id}/` retires a zone (`is_active=False`); rows are never deleted
    because historical `Delivery.zone` references them.
23. **The quote walks `StoreDeliveryPartner` by priority.** The first active
    contracted company with an active zone covering the address wins; a company
    that does not cover it is skipped and the next partner is tried. This is why
    the store's `delivery_companies` list and the quote can disagree on a given
    address.
24. **Checkout locks the quote.** `Delivery` is created with the quoted `company`,
    `zone` and `fee` and `cash_to_collect = order.total`; later zone edits,
    re-pricing or contract changes never touch an existing order.
25. **The offer pool has no per-courier expiry this pass.** `ready` moves the
    `Delivery` to `requested`; it stays in the company's pool until a courier
    accepts, the dispatcher assigns, or the company releases or fails it. The 90 s
    `offered` timeout and its Celery sweep return with the tracking work.
26. **`transition()` takes `request_delivery=True`.** `ready` requests the company;
    `release` puts the order back to `ready` with `request_delivery=False` so the
    job is not instantly bounced back to the company that just gave it up, while
    `fail` re-requests it (`assign_attempts` still increments).
27. **`select_for_update(of=("self",))` wherever the lock joins `company`.** The
    `Delivery.company` FK is nullable, and Postgres refuses `FOR UPDATE` on the
    nullable side of an outer join; locking only `Delivery` keeps the row lock
    without the error.
28. **`CompanyStatus` reuses the `StoreStatus` schema component.** Both enums have
    the same choices; drf-spectacular errors when two names map to one choice set,
    so `ENUM_NAME_OVERRIDES` registers only `StoreStatusEnum` and a company's
    `status` documents as `StoreStatusEnum`.
29. **Notifications are rows first, push second.** `notify()` writes the
    `Notification` inside the transaction that caused it and sends the push on
    commit; the adapter in `notifications/push.py` only logs until FCM credentials
    exist, so a dead provider loses nothing the app cannot read over REST.
    `GET /notifications/` is open to every signed-in role and scoped to the user;
    a failed delivery attempt is deliberately silent for the customer.
30. **Tracking is write-over-HTTP, read-over-socket.** The courier's `PATCH
    .../location/` updates `CourierLocation`, samples `DeliveryLocationPing` and
    then broadcasts; the socket never accepts frames. Broadcasts are best effort
    (a channel-layer failure is logged, never raised) and locations are throttled
    to one frame per second per delivery, while the stored trail stays at one ping
    per minute. `TrackingConsumer` authorises from a 60 s `TrackingTicket` JWT
    scoped to one delivery, not from a session, and closes with 4401 for a bad or
    mismatched ticket and 4403 for a user who may not watch it.
31. **ASGI runs on daphne; tests never touch Redis.** `config.asgi` mounts
    `ProtocolTypeRouter` with `delivery.routing`, and `config/settings/test.py`
    swaps `CHANNEL_LAYERS` for the in-memory backend and makes Celery eager, so
    `pytest` needs neither a broker nor a channel layer in WSL.
32. **A review is one row per delivered item and never changes.** `Review` is
    one-to-one with `OrderItem`; `post_review()` refuses anything but a
    `delivered` order, and only the store's `store_reply`/`replied_at` are
    writable afterwards. `Product.avg_rating`/`rating_count` are recomputed from
    the review rows after each post, so they cannot drift. The customer's order
    item is the only way in and is scoped to the customer (404 otherwise).
    `GET /stores/{slug}/reviews/` is public and lists the store's reviews.
33. **Coupons are scoped by the view, retired by `is_active`.** The dashboard
    pins `store=request.store`, the platform surface pins `store=None`; delete
    deactivates rather than removing a row that redemptions point at. Codes are
    checked case-insensitively inside their own scope (`code` for platform,
    `(store, code)` for a store), percent discounts cap at 100, and
    `ends_at > starts_at`. Redemption and `used_count` still change only at
    checkout.
34. **The ledger is written at fulfilment, never edited.** `delivered` writes a
    `sale` row for `subtotal - discount_total` (commission = goods × the store's
    `commission_rate`) and a separate `commission` row for the delivery fee
    (commission = fee × the company's `commission_rate`). A refund appends the
    negation of both instead of updating them. Writes are synchronous inside
    `transition()` and idempotent; the Celery task is only a retry net.
    `delivered → refunded` is the one move out of a terminal state and stays
    super-admin only (decision 18: COD goods are already with the customer).
35. **Rollups bucket a day in `REPORT_TIME_ZONE` (`Asia/Damascus`), not UTC.**
    `rollup_stats` recomputes a day from current state with `update_or_create`,
    so reruns and late cancellations are safe; beat runs it at 00:15. Anything
    before today is read from `DailyStoreStat`/`DailyProductStat`, today is
    queried live. Platform revenue reads the ledger directly because it spans
    stores and every row already carries the platform's cut.
36. **Settlement is a weekly `Payout` per store and company, and it is frozen
    once settled.** `materialise_payouts` rolls one Mon–Sun week of ledger rows
    into one row per `(store, order.delivery.company)`: `cash_collected` is the
    sum of `gross`, `platform_commission` the sum of `commission`, `store_net`
    the net of the goods lines and `company_net` the net of the fee lines
    (`LedgerEntry.delivery_id is not None` marks a fee line, because a sale row
    never carries a delivery). The identity
    `cash_collected == store_net + company_net + platform_commission` holds by
    construction. `pending → settled → paid`; a settled or paid row is never
    rewritten, so a late ledger row waits for the next week instead of changing
    money already handed over. `mark-paid` appends a `LedgerEntry(kind=payout)`
    for `store_net` rather than editing the week, and the platform revenue
    series excludes `payout` rows so paying a store does not inflate commission.
    `Payout` lives in `analytics` (`analytics.0002_payout`); the company owes the
    store, so the row carries both parties and the platform's cut.
37. **Scheduled jobs act as `orders.services.SYSTEM`, never as a user.**
    `SystemActor` carries a super admin's capabilities but is not a user row, so
    `transition()` stores `actor=NULL` and `actor_role="system"` on the
    `OrderStatusEvent`; `InventoryMovement.created_by` and the `DeliveryEvent`
    actor are NULL for the same reason. `cancel_stale_pending_orders` (beat,
    every 5 minutes) cancels `pending` orders older than 30 minutes through that
    actor, so stock is restored and both the customer and the store are notified
    exactly as for a manual cancel; a race with the store is a logged skip, not
    an error. `prune_location_pings` (beat, Sunday 03:00) deletes trail rows
    older than 30 days and leaves `CourierLocation`, the latest position,
    untouched.

38. **The published contract is a gated Scalar page, and it cannot drift.**
    `/api/docs/` renders Scalar (`backend/templates/api/docs.html`) against the
    schema this process generates, embedded in the page rather than fetched —
    a gated page must not depend on the browser replaying Basic credentials to
    a `fetch()`. Swagger UI moves to `/api/docs/swagger/` and stays as the
    do-everything fallback; `/api/schema/` remains the file clients generate
    from. `core.middleware.DocsGateMiddleware` puts all four routes behind one
    shared Basic credential (`DOCS_AUTH_USER`/`DOCS_AUTH_PASSWORD`), and since
    the schema names every endpoint including `/platform/`, it **fails closed**:
    with no credential configured a production process answers 404, while DEBUG
    stays open. The Scalar bundle is vendored at
    `backend/static/vendor/scalar-1.76.4.js` (MIT) so the docs work on a network
    that cannot reach a CDN, and `tests/test_docs.py` compares the live
    generator to the committed `schema.yml`, so a forgotten `spectacular` run
    fails the suite instead of the page lying.

39. **Deployment is one image and one compose file, and the image is the
    backend's own.** `backend/Dockerfile` (Python 3.14 slim, non-root) builds
    once and runs as `api`, `worker` or `beat` through
    `backend/docker-entrypoint.sh`; the api role migrates, collects static and
    serves ASGI with daphne — gunicorn is out because the tracking socket needs
    ASGI. Static files are served by WhiteNoise from that same container, so
    `/api/docs/` needs no Nginx and no second deploy. `docker-compose.yml` at the
    repository root adds Postgres 16, Redis and the three roles, publishes no
    host port, and is the artifact Coolify deploys; `/healthz/` exists for its
    healthchecks and is exempt from `SECURE_SSL_REDIRECT` so the check does not
    chase a 301 into a TLS handshake that cannot happen inside the container.
    The live host is **`multi-store.georgesalebe.me`**, and the compose defaults
    now name it: `ALLOWED_HOSTS` carries it plus `localhost`/`127.0.0.1` so the
    container's own healthcheck is not a `DisallowedHost`, `CSRF_TRUSTED_ORIGINS`
    carries `https://` for it, and `SECURE_SSL_REDIRECT` defaults to True because
    Traefik terminates TLS and forwards `X-Forwarded-Proto`. A plain-http local
    `docker compose up` therefore passes `SECURE_SSL_REDIRECT=False`, and the
    local override publishes the API on **8010** so it can never be confused
    with the container port or with the Coolify dashboard, which owns host port
    8000 on a Coolify box.

40. **The database password belongs to the volume, so it is required and it
    fails loudly.** `SECRET_KEY` and `POSTGRES_PASSWORD` are `${VAR:?}` in
    `docker-compose.yml`: an empty one stops the deploy instead of running with
    a committed default that signs forgeable JWTs or a database anyone on the
    network could open. `POSTGRES_PASSWORD` is also read **only when the
    `pgdata` volume is empty** — after initdb it is a property of the volume, so
    editing the variable and redeploying produces
    `password authentication failed for user ...` and an api that crash-loops
    while the db still looks fine. Two consequences are recorded here so nobody
    re-learns them the hard way. The db healthcheck logs in with those
    credentials (`PGPASSWORD=… psql -h 127.0.0.1 -c 'select 1'`) instead of
    `pg_isready`, which only proves the server is listening; the forced TCP host
    is the part that makes it real, because the image trusts the local socket,
    so a socket login would succeed with any password. A mismatch now makes the
    database the unhealthy container. And the api entrypoint wraps `migrate`
    with a plain-language hint pointing at `ALTER USER` (or deleting a fresh
    volume), because the raw Django traceback reads like a code bug. Rotation is
    `ALTER USER` in the running container, never a variable edit; the password
    stays `A-Za-z0-9` because it is interpolated into `DATABASE_URL`, where
    `@ : / ? #` would corrupt the DSN.

41. **Every operation's summary and description lives in one table.**
    `config/api_text.py` maps `(METHOD, path)` — as the schema prints it, so
    `{id}` and `{item_pk}` — to a `Text(summary, description)`, and
    `apply_operation_text` puts that on the operation as a drf-spectacular
    `POSTPROCESSING_HOOKS` entry. The text is central rather than written as
    `@extend_schema(summary=...)` on each view because there are 157 operations
    across twenty view modules and most views are class-based with several
    methods; the annotation route fails silently when a new endpoint is added
    without one, while here `tests/test_docs.py` asserts that every operation
    carries exactly the table's text and that no table key is orphaned by a
    renamed path. Descriptions say what the schema cannot: scope
    (`request.store`), the rules with an HTTP consequence (`404` cross-tenant,
    `409` illegal transition, `422` out of stock) and stateful requirements
    (`Idempotency-Key`). Field lists and the global money/UUID conventions stay
    out, since the components already say them. Summaries stay within 60
    characters and descriptions within 240 so they fit a Scalar card. This
    also removes the accidental descriptions that came from
    `ReadWritePermissionsMixin`'s docstring, which `inspect.getdoc` had been
    inheriting into every view that uses the mixin.

42. **Rate limits are scoped, shared through Redis, and documented.**
    `DEFAULT_THROTTLE_CLASSES` gives every operation an anonymous (60/min) and
    per-user (300/min) budget. `core.throttling.ScopedThrottleMixin` adds a
    named bucket on the views where that default is the wrong shape: `auth`
    20/min on register, login, refresh and password change; `password-reset`
    5/hour; `checkout` 20/min; `checkout-preview` and the anonymous `quote`
    60/min; `ticket` 30/min; `location` 120/min; `review` and `invite` 20/hour.
    A view that names a scope keeps the two global buckets, because overriding
    `throttle_classes` with `ScopedRateThrottle` alone would silently drop
    them. DRF answers `429` with `Retry-After`, and `config.api_errors` adds
    that response to every operation — drf-spectacular 0.28 cannot infer
    throttling, so without the hook the reference page would never mention it.
    Counters live in the cache: production points this at the same Redis the
    broker uses, because LocMem would let each api container hand out a full
    budget. `test.py` raises every ceiling so only a test that patches the
    rates exercises the limiter. Login has no per-email lockout yet; per-IP
    throttling is the first line, and distributed credential stuffing needs an
    account-level counter (recorded in `API_AUDIT.md` as a follow-up).
