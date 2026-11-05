"""One summary and one description per API operation, for the reference page.

Scalar (and Swagger) label an operation with its `summary` and explain it with
its `description`. drf-spectacular can only derive those from a view's extend
schema or docstring, which meant the 148 operations came out mostly bare — and
the forty that did have text were showing the base permission class's docstring.
Keeping the text in one table instead of scattering it over twenty view modules
means it can be read end to end, diffed against `AGENTS.md` section 9, and
checked in one test: `tests/test_docs.py` asserts every operation carries
exactly the text below and that no key here is orphaned by a renamed path.

Keys are `(METHOD, path)` as they appear in the generated schema, so path
parameters read `{id}` and `{item_id}`, not the `{pk}` of the URL conf.
"""

from typing import NamedTuple


class Text(NamedTuple):
    summary: str
    description: str


OPERATIONS: dict[tuple[str, str], Text] = {
    # ------------------------------------------------------------------
    # auth
    # ------------------------------------------------------------------
    ("POST", "/api/v1/auth/register/"): Text(
        "Create a customer account",
        "Public signup. Returns the new user with an access and refresh token pair.",
    ),
    ("POST", "/api/v1/auth/login/"): Text(
        "Sign in",
        "Email and password in, access and refresh tokens out, with the user's role and profile.",
    ),
    ("POST", "/api/v1/auth/refresh/"): Text(
        "Refresh an access token",
        "Exchanges a valid refresh token for a new access token and, because "
        "rotation is on, a new refresh token.",
    ),
    ("POST", "/api/v1/auth/logout/"): Text(
        "Sign out",
        "Blacklists the supplied refresh token so it cannot be replayed. The access "
        "token expires on its own within 15 minutes.",
    ),
    ("GET", "/api/v1/auth/me/"): Text(
        "Get your profile",
        "The signed-in user's account: email, name, phone and role.",
    ),
    ("PATCH", "/api/v1/auth/me/"): Text(
        "Update your profile",
        "Partial update of the writable profile fields, the name and phone.",
    ),
    ("POST", "/api/v1/auth/password/change/"): Text(
        "Change your password",
        "Requires the current password. The new one must pass the configured password validators.",
    ),
    ("POST", "/api/v1/auth/password/reset/"): Text(
        "Request a password reset",
        "Emails a single-use reset link to the address. Always answers 204, so the "
        "endpoint cannot be used to enumerate accounts.",
    ),
    ("POST", "/api/v1/auth/password/reset/confirm/"): Text(
        "Complete a password reset",
        "Takes the token from the emailed link and the new password.",
    ),
    ("GET", "/api/v1/auth/device-tokens/"): Text(
        "List your device tokens",
        "The push tokens registered for this account. Paginated and orderable like every list.",
    ),
    ("POST", "/api/v1/auth/device-tokens/"): Text(
        "Register a device token",
        "Stores an FCM token for push notifications, or reactivates the same token "
        "if it is already known.",
    ),
    ("DELETE", "/api/v1/auth/device-tokens/{id}/"): Text(
        "Remove a device token",
        "Stops push notifications to that device. Only the owner's tokens are "
        "visible; anyone else's is 404.",
    ),
    # ------------------------------------------------------------------
    # company
    # ------------------------------------------------------------------
    ("GET", "/api/v1/company/profile/"): Text(
        "Get your delivery company",
        "Scoped to `request.company`. Status and commission rate are platform-run and read-only.",
    ),
    ("PATCH", "/api/v1/company/profile/"): Text(
        "Update your delivery company",
        "Partial update of the company profile.",
    ),
    ("GET", "/api/v1/company/members/"): Text(
        "List the company's team",
        "Memberships of `request.company`, with each member's role and active flag.",
    ),
    ("POST", "/api/v1/company/members/invite/"): Text(
        "Invite a team member",
        "Creates a delivery-staff account, or attaches an existing one, to the "
        "company. Owner and manager only.",
    ),
    ("PATCH", "/api/v1/company/members/{id}/"): Text(
        "Update a team member",
        "Changes role or active state. The owner's role is fixed, and a member of "
        "another company is 404.",
    ),
    ("GET", "/api/v1/company/couriers/"): Text(
        "List the company's couriers",
        "The riders employed by `request.company`. Filter with `is_available`, search with `q`.",
    ),
    ("POST", "/api/v1/company/couriers/"): Text(
        "Hire a courier",
        "Creates a courier account tied to this company. Stores never create "
        "couriers, only the company that employs them does.",
    ),
    ("PATCH", "/api/v1/company/couriers/{id}/"): Text(
        "Update a courier",
        "Vehicle, plate and availability. Set `is_active: false` to end the "
        "employment without deleting history.",
    ),
    ("GET", "/api/v1/company/zones/"): Text(
        "List delivery zones",
        "The company's coverage areas: centre, radius, fee, minimum order and ETA.",
    ),
    ("POST", "/api/v1/company/zones/"): Text(
        "Create a delivery zone",
        "A new coverage area. The fee and minimum order set here are what checkout "
        "quotes to customers.",
    ),
    ("GET", "/api/v1/company/zones/{id}/"): Text(
        "Get a delivery zone",
        "One zone of `request.company`; another company's zone is 404.",
    ),
    ("PATCH", "/api/v1/company/zones/{id}/"): Text(
        "Update a delivery zone",
        "Partial update of the coverage area. Orders already placed keep the fee they were quoted.",
    ),
    ("DELETE", "/api/v1/company/zones/{id}/"): Text(
        "Retire a delivery zone",
        "Sets `is_active` to false rather than deleting: past deliveries still reference the zone.",
    ),
    ("GET", "/api/v1/company/deliveries/"): Text(
        "List the company's jobs",
        "The job pool and active work. Filter by `status`, `courier` or `active`.",
    ),
    ("GET", "/api/v1/company/deliveries/{id}/"): Text(
        "Get a job",
        "One delivery with its order items and its event trail.",
    ),
    ("POST", "/api/v1/company/deliveries/{id}/assign/"): Text(
        "Assign a job to a courier",
        "Takes `courier_id` and also accepts a requested job straight out of the "
        "pool. The courier must work for this company.",
    ),
    ("POST", "/api/v1/company/deliveries/{id}/release/"): Text(
        "Release a job",
        "Hands the job back: the order returns to `ready` and is not immediately "
        "re-offered to the same company.",
    ),
    ("POST", "/api/v1/company/deliveries/{id}/fail/"): Text(
        "Fail a delivery attempt",
        "Requires a reason. The order returns to `ready` and is re-offered, with "
        "`assign_attempts` incremented.",
    ),
    ("GET", "/api/v1/company/earnings/"): Text(
        "Get company earnings",
        "COD collected, gross delivery fees, the platform's commission and the net "
        "over `from`-`to`.",
    ),
    ("GET", "/api/v1/company/deliveries/{id}/ws-ticket/"): Text(
        "Get a dispatch tracking ticket",
        "A 60-second WebSocket ticket for one of this company's deliveries, for the "
        "dispatcher's map.",
    ),
    # ------------------------------------------------------------------
    # courier
    # ------------------------------------------------------------------
    ("GET", "/api/v1/courier/me/"): Text(
        "Get your courier profile",
        "Vehicle, plate, availability and today's delivery stats.",
    ),
    ("PATCH", "/api/v1/courier/availability/"): Text(
        "Set your availability",
        "`is_available` controls whether the dispatcher may assign you new jobs.",
    ),
    ("GET", "/api/v1/courier/offers/"): Text(
        "List offered jobs",
        "Requested jobs in your company's pool, which any courier there may accept.",
    ),
    ("GET", "/api/v1/courier/deliveries/"): Text(
        "List your deliveries",
        "Only jobs assigned to you. Filter by `status` or `active`.",
    ),
    ("GET", "/api/v1/courier/deliveries/{id}/"): Text(
        "Get your delivery",
        "One of your deliveries with pickup and drop coordinates, items and the cash to collect.",
    ),
    ("POST", "/api/v1/courier/deliveries/{id}/accept/"): Text(
        "Accept an offered job",
        "Assigns the job to you and moves the order to `assigned`. Another courier "
        "taking it first is 409.",
    ),
    ("POST", "/api/v1/courier/deliveries/{id}/decline/"): Text(
        "Decline an offered job",
        "Optional note. The job stays in the company's pool for another courier.",
    ),
    ("POST", "/api/v1/courier/deliveries/{id}/pickup/"): Text(
        "Mark a delivery picked up",
        "Moves the order to `out_for_delivery`. The job must be accepted first.",
    ),
    ("PATCH", "/api/v1/courier/deliveries/{id}/location/"): Text(
        "Report your location",
        "Updates the latest position, samples the trail at most once a minute and "
        "broadcasts to everyone watching the delivery.",
    ),
    ("POST", "/api/v1/courier/deliveries/{id}/deliver/"): Text(
        "Complete a delivery",
        "Optionally verifies the OTP and stores a proof photo. Records the cash "
        "collected and moves the order to `delivered`.",
    ),
    ("POST", "/api/v1/courier/deliveries/{id}/fail/"): Text(
        "Fail a delivery",
        "Requires a reason. The order returns to `ready` and the attempt is logged.",
    ),
    ("GET", "/api/v1/courier/earnings/"): Text(
        "Get your earnings",
        "COD cash you collected and the number of deliveries completed over `from`-`to`.",
    ),
    ("GET", "/api/v1/courier/deliveries/{id}/ws-ticket/"): Text(
        "Get a delivery tracking ticket",
        "A 60-second WebSocket ticket for one of your deliveries.",
    ),
    # ------------------------------------------------------------------
    # dashboard
    # ------------------------------------------------------------------
    ("GET", "/api/v1/dashboard/store/"): Text(
        "Get your store",
        "Scoped to `request.store`. Status and commission rate are platform-run and read-only.",
    ),
    ("PATCH", "/api/v1/dashboard/store/"): Text(
        "Update your store",
        "Partial update of the store profile, including whether it is accepting orders.",
    ),
    ("GET", "/api/v1/dashboard/opening-hours/"): Text(
        "Get opening hours",
        "One row per weekday, with `is_closed` marking the days the store shuts.",
    ),
    ("PATCH", "/api/v1/dashboard/opening-hours/"): Text(
        "Replace opening hours",
        "Bulk write of all seven days in one request.",
    ),
    ("GET", "/api/v1/dashboard/categories/"): Text(
        "List categories",
        "The store's own categories.",
    ),
    ("POST", "/api/v1/dashboard/categories/"): Text(
        "Create a category",
        "A category pinned to `request.store`. A parent category from another store is 422.",
    ),
    ("GET", "/api/v1/dashboard/categories/{id}/"): Text(
        "Get a category",
        "One of the store's categories; another store's is 404.",
    ),
    ("PATCH", "/api/v1/dashboard/categories/{id}/"): Text(
        "Update a category",
        "Partial update of a category.",
    ),
    ("DELETE", "/api/v1/dashboard/categories/{id}/"): Text(
        "Retire a category",
        "Sets `is_active` to false; products keep their reference to it.",
    ),
    ("GET", "/api/v1/dashboard/products/"): Text(
        "List products",
        "The store's catalog. Filter by `status` and `category`, search with `q`.",
    ),
    ("POST", "/api/v1/dashboard/products/"): Text(
        "Create a product",
        "Creates a draft product. A category from another store is 422.",
    ),
    ("GET", "/api/v1/dashboard/products/{id}/"): Text(
        "Get a product",
        "The product with its images and variants.",
    ),
    ("PATCH", "/api/v1/dashboard/products/{id}/"): Text(
        "Update a product",
        "Partial update of the product.",
    ),
    ("DELETE", "/api/v1/dashboard/products/{id}/"): Text(
        "Archive a product",
        "Sets the status to `archived` and returns the product. Nothing that appears "
        "on an order is ever deleted.",
    ),
    ("POST", "/api/v1/dashboard/products/{id}/images/"): Text(
        "Upload a product image",
        "Multipart upload with `image`, plus optional `alt` and `sort_order`.",
    ),
    ("POST", "/api/v1/dashboard/products/{id}/variants/"): Text(
        "Add a product variant",
        "A variant carries its own SKU, price, compare-at price and stock.",
    ),
    ("PATCH", "/api/v1/dashboard/variants/{id}/"): Text(
        "Update a variant",
        "Price, label and active flag. Stock never changes here.",
    ),
    ("POST", "/api/v1/dashboard/variants/{id}/stock/"): Text(
        "Adjust stock",
        "Writes an append-only `InventoryMovement`. A delta that would take stock "
        "below zero is 422.",
    ),
    ("GET", "/api/v1/dashboard/inventory-movements/"): Text(
        "List stock movements",
        "The audit trail for the store's variants. Filter by `variant`.",
    ),
    ("GET", "/api/v1/dashboard/companies/"): Text(
        "List contractable companies",
        "Active delivery companies the store may contract.",
    ),
    ("GET", "/api/v1/dashboard/partners/"): Text(
        "List delivery partners",
        "The store's contracts, with priority and active flag.",
    ),
    ("POST", "/api/v1/dashboard/partners/"): Text(
        "Contract a delivery company",
        "Takes `company_id` and `priority`, lower being tried first. The company must be active.",
    ),
    ("PATCH", "/api/v1/dashboard/partners/{id}/"): Text(
        "Update a contract",
        "Priority or active flag of one contract.",
    ),
    ("DELETE", "/api/v1/dashboard/partners/{id}/"): Text(
        "End a contract",
        "Sets `is_active` to false. Deliveries already placed keep their company.",
    ),
    ("GET", "/api/v1/dashboard/deliveries/"): Text(
        "List the store's deliveries",
        "Deliveries for this store's orders. Filter by `status` or `company`.",
    ),
    ("GET", "/api/v1/dashboard/deliveries/{id}/"): Text(
        "Get a store delivery",
        "One of the store's deliveries with its event trail.",
    ),
    ("POST", "/api/v1/dashboard/deliveries/{id}/request/"): Text(
        "Request a delivery",
        "Re-offers a ready order, optionally to a stated `company_id`. The order must be `ready`.",
    ),
    ("GET", "/api/v1/dashboard/orders/"): Text(
        "List the store's orders",
        "Filter by `status` and `from`/`to`, or search by order number with `q`.",
    ),
    ("GET", "/api/v1/dashboard/orders/{id}/"): Text(
        "Get an order",
        "One of the store's orders with items, totals and status history.",
    ),
    ("POST", "/api/v1/dashboard/orders/{id}/confirm/"): Text(
        "Confirm an order",
        "`pending` to `confirmed`. Another store's order is 404, an illegal move 409.",
    ),
    ("POST", "/api/v1/dashboard/orders/{id}/preparing/"): Text(
        "Start preparing an order",
        "`confirmed` to `preparing`.",
    ),
    ("POST", "/api/v1/dashboard/orders/{id}/ready/"): Text(
        "Mark an order ready",
        "`preparing` to `ready`, and asks the first contracted company that covers "
        "the address to take the job.",
    ),
    ("POST", "/api/v1/dashboard/orders/{id}/cancel/"): Text(
        "Cancel an order",
        "From `pending`, `confirmed`, `preparing` or `ready`. Restores stock and "
        "cancels the delivery.",
    ),
    ("GET", "/api/v1/dashboard/orders/{id}/ws-ticket/"): Text(
        "Get an order tracking ticket",
        "A 60-second WebSocket ticket for one of the store's orders.",
    ),
    ("GET", "/api/v1/dashboard/coupons/"): Text(
        "List coupons",
        "The store's own coupons. Platform-wide coupons are not listed here.",
    ),
    ("POST", "/api/v1/dashboard/coupons/"): Text(
        "Create a coupon",
        "A coupon pinned to `request.store`. Codes are unique per store and compared "
        "case-insensitively.",
    ),
    ("GET", "/api/v1/dashboard/coupons/{id}/"): Text(
        "Get a coupon",
        "One of the store's coupons with its usage count.",
    ),
    ("PATCH", "/api/v1/dashboard/coupons/{id}/"): Text(
        "Update a coupon",
        "Partial update of a coupon.",
    ),
    ("DELETE", "/api/v1/dashboard/coupons/{id}/"): Text(
        "Deactivate a coupon",
        "Sets `is_active` to false; redemptions still point at the row.",
    ),
    ("GET", "/api/v1/dashboard/reviews/"): Text(
        "List reviews",
        "Reviews left on this store's delivered items.",
    ),
    ("POST", "/api/v1/dashboard/reviews/{id}/reply/"): Text(
        "Reply to a review",
        "Writes `store_reply` and stamps `replied_at`. This is the only writable "
        "field on a review.",
    ),
    ("GET", "/api/v1/dashboard/insights/summary/"): Text(
        "Get the sales summary",
        "Orders, gross and net sales, delivery fees, discounts and average order "
        "value over `from`-`to`.",
    ),
    ("GET", "/api/v1/dashboard/insights/revenue/"): Text(
        "Get the revenue series",
        "Daily sales over `from`-`to`. Past days come from the rollups, today is queried live.",
    ),
    ("GET", "/api/v1/dashboard/insights/top-products/"): Text(
        "Get top products",
        "Best sellers by quantity and revenue over `from`-`to`.",
    ),
    ("GET", "/api/v1/dashboard/insights/orders-by-status/"): Text(
        "Get orders by status",
        "Order counts per status over `from`-`to`.",
    ),
    ("GET", "/api/v1/dashboard/insights/delivery-performance/"): Text(
        "Get delivery performance",
        "Average delivery time and failure rate over `from`-`to`.",
    ),
    ("GET", "/api/v1/dashboard/ledger/"): Text(
        "List ledger entries",
        "The store's append-only money rows. Filter by `kind` and `from`/`to`.",
    ),
    # ------------------------------------------------------------------
    # platform
    # ------------------------------------------------------------------
    ("GET", "/api/v1/platform/stores/"): Text(
        "List all stores",
        "Every store on the platform, whatever its status.",
    ),
    ("POST", "/api/v1/platform/stores/"): Text(
        "Onboard a store",
        "Creates the store and its owner account as `pending`. The owner gets the "
        "`store_admin` role.",
    ),
    ("GET", "/api/v1/platform/stores/{id}/"): Text(
        "Get a store",
        "Full platform view of one store, including its owner and status.",
    ),
    ("POST", "/api/v1/platform/stores/{id}/approve/"): Text(
        "Approve a store",
        "`pending` to `active`, which makes it visible in the public store list.",
    ),
    ("POST", "/api/v1/platform/stores/{id}/suspend/"): Text(
        "Suspend a store",
        "Requires a reason. The store leaves the public list and stops accepting orders.",
    ),
    ("GET", "/api/v1/platform/companies/"): Text(
        "List delivery companies",
        "Every delivery company, whatever its status.",
    ),
    ("POST", "/api/v1/platform/companies/"): Text(
        "Onboard a delivery company",
        "Creates the company and its owner as `pending`. The owner gets the `delivery_admin` role.",
    ),
    ("GET", "/api/v1/platform/companies/{id}/"): Text(
        "Get a delivery company",
        "Full platform view of one company, including its owner and status.",
    ),
    ("POST", "/api/v1/platform/companies/{id}/approve/"): Text(
        "Approve a delivery company",
        "`pending` to `active`, so stores may contract it.",
    ),
    ("POST", "/api/v1/platform/companies/{id}/suspend/"): Text(
        "Suspend a delivery company",
        "Requires a reason. Suspension stops the company accepting new jobs.",
    ),
    ("GET", "/api/v1/platform/users/"): Text(
        "List users",
        "Every account, with its role and active state. Search by name or email.",
    ),
    ("PATCH", "/api/v1/platform/users/{id}/"): Text(
        "Update a user",
        "Activates or deactivates an account, or corrects its name. Email and role "
        "are not editable here.",
    ),
    ("GET", "/api/v1/platform/orders/"): Text(
        "List all orders",
        "Orders across every store. Filter by `status`, `store` and `from`/`to`.",
    ),
    ("GET", "/api/v1/platform/deliveries/"): Text(
        "List all deliveries",
        "Deliveries across every company. Filter by `status`, `company`, `store` and `from`/`to`.",
    ),
    ("GET", "/api/v1/platform/coupons/"): Text(
        "List platform coupons",
        "Only platform-wide coupons, the ones with no store, not the stores' own.",
    ),
    ("POST", "/api/v1/platform/coupons/"): Text(
        "Create a platform coupon",
        "A coupon valid in every store. The code is unique across the platform.",
    ),
    ("GET", "/api/v1/platform/insights/overview/"): Text(
        "Get the platform overview",
        "GMV, order counts, active stores and active companies over `from`-`to`.",
    ),
    ("GET", "/api/v1/platform/insights/revenue/"): Text(
        "Get platform revenue",
        "Commission earned per day over `from`-`to`, read from the ledger.",
    ),
    ("GET", "/api/v1/platform/ledger/"): Text(
        "List the platform ledger",
        "Every store's ledger rows. Filter by `store`, `kind` and `from`/`to`.",
    ),
    ("GET", "/api/v1/platform/payouts/"): Text(
        "List payouts",
        "Weekly settlements per store and company. Filter by `store`, `company`, "
        "`status` and `from`/`to`.",
    ),
    ("POST", "/api/v1/platform/payouts/{id}/settle/"): Text(
        "Settle a payout",
        "`pending` to `settled`: the company handed the COD cash over. A settled row "
        "is frozen from then on.",
    ),
    ("POST", "/api/v1/platform/payouts/{id}/mark-paid/"): Text(
        "Mark a payout paid",
        "`settled` to `paid`. Appends a `LedgerEntry` of kind `payout` for the "
        "store's net instead of editing the week.",
    ),
    # ------------------------------------------------------------------
    # addresses
    # ------------------------------------------------------------------
    ("GET", "/api/v1/addresses/"): Text(
        "List your addresses",
        "The signed-in customer's saved addresses, including the default one.",
    ),
    ("POST", "/api/v1/addresses/"): Text(
        "Create an address",
        "A delivery address with optional coordinates. Setting `is_default` clears "
        "the previous default.",
    ),
    ("GET", "/api/v1/addresses/{id}/"): Text(
        "Get an address",
        "One of the customer's addresses; another customer's is 404.",
    ),
    ("PATCH", "/api/v1/addresses/{id}/"): Text(
        "Update an address",
        "Partial update of the address.",
    ),
    ("DELETE", "/api/v1/addresses/{id}/"): Text(
        "Delete an address",
        "Removes the address. Past orders keep their own snapshot, so history does not change.",
    ),
    ("POST", "/api/v1/addresses/{id}/set-default/"): Text(
        "Set the default address",
        "Makes this the customer's default and clears the flag on the previous one.",
    ),
    # ------------------------------------------------------------------
    # cart
    # ------------------------------------------------------------------
    ("GET", "/api/v1/carts/"): Text(
        "List your carts",
        "One cart per store, so a customer can shop several stores before checking out.",
    ),
    ("POST", "/api/v1/carts/"): Text(
        "Open a cart",
        "Get-or-create the cart for one store: 200 if it existed, 201 if it was created.",
    ),
    ("POST", "/api/v1/carts/{id}/items/"): Text(
        "Add an item",
        "Adds a variant or increases its quantity. More than the available stock is 422.",
    ),
    ("PATCH", "/api/v1/carts/{id}/items/{item_id}/"): Text(
        "Change an item's quantity",
        "Sets the quantity. A quantity of 0 removes the item and answers 204.",
    ),
    ("DELETE", "/api/v1/carts/{id}/items/{item_id}/"): Text(
        "Remove an item",
        "Removes the line from the cart.",
    ),
    ("POST", "/api/v1/carts/{id}/coupon/"): Text(
        "Apply a coupon",
        "Validates the code against this cart's subtotal now, and checkout validates it again.",
    ),
    ("DELETE", "/api/v1/carts/{id}/coupon/"): Text(
        "Remove the coupon",
        "Detaches the coupon from the cart without touching its usage count.",
    ),
    ("POST", "/api/v1/carts/{id}/clear/"): Text(
        "Clear the cart",
        "Empties the cart but keeps it open.",
    ),
    # ------------------------------------------------------------------
    # notifications
    # ------------------------------------------------------------------
    ("GET", "/api/v1/notifications/"): Text(
        "List notifications",
        "The signed-in user's notifications, newest first. `unread=true` narrows the list.",
    ),
    ("POST", "/api/v1/notifications/{id}/read/"): Text(
        "Mark a notification read",
        "Stamps `read_at`. Only the owner's notifications are visible.",
    ),
    ("POST", "/api/v1/notifications/read-all/"): Text(
        "Mark all notifications read",
        "Stamps every unread notification of the signed-in user.",
    ),
    # ------------------------------------------------------------------
    # orders
    # ------------------------------------------------------------------
    ("GET", "/api/v1/checkout/preview/"): Text(
        "Preview checkout",
        "Per-store subtotal, delivery fee, discount and total, plus anything "
        "blocking checkout. Takes `address_id` and `store_ids`.",
    ),
    ("POST", "/api/v1/checkout/"): Text(
        "Check out",
        "Requires an `Idempotency-Key` header; replaying the key returns the "
        "original group. Produces one order per store.",
    ),
    ("GET", "/api/v1/checkout-groups/"): Text(
        "List checkout groups",
        "The customer's checkout history; each group holds the orders placed in one action.",
    ),
    ("GET", "/api/v1/checkout-groups/{id}/"): Text(
        "Get a checkout group",
        "One group with its orders nested.",
    ),
    ("GET", "/api/v1/orders/"): Text(
        "List your orders",
        "Filter by `status`, `store` and `from`/`to`.",
    ),
    ("GET", "/api/v1/orders/{id}/"): Text(
        "Get an order",
        "With items, totals and the delivery, once one exists.",
    ),
    ("GET", "/api/v1/orders/{id}/timeline/"): Text(
        "Get an order's timeline",
        "Every status event in order, with the actor's role and any note.",
    ),
    ("POST", "/api/v1/orders/{id}/cancel/"): Text(
        "Cancel your order",
        "Allowed while `pending` or `confirmed`. Restores stock and cancels the delivery.",
    ),
    ("GET", "/api/v1/orders/{id}/ws-ticket/"): Text(
        "Get your order's tracking ticket",
        "A 60-second WebSocket ticket for watching this order's courier.",
    ),
    # ------------------------------------------------------------------
    # reviews
    # ------------------------------------------------------------------
    ("POST", "/api/v1/order-items/{id}/review/"): Text(
        "Review a delivered item",
        "One review per order item, only after the order is `delivered`. Rating 1-5 "
        "with an optional comment.",
    ),
    # ------------------------------------------------------------------
    # public
    # ------------------------------------------------------------------
    ("GET", "/api/v1/stores/"): Text(
        "Browse stores",
        "Active stores only. Search with `q`, or pass `lat` and `lng`, plus "
        "`radius`, to find the nearby ones.",
    ),
    ("GET", "/api/v1/stores/{store_slug}/products/{slug}/"): Text(
        "Get a storefront product",
        "A product of an active store, with its images and variants.",
    ),
    ("GET", "/api/v1/stores/{slug}/products/"): Text(
        "List a store's products",
        "Filter by `category`, `min_price` and `max_price`, `in_stock`, and search with `q`.",
    ),
    ("GET", "/api/v1/stores/{slug}/categories/"): Text(
        "List a store's categories",
        "The categories of one active store.",
    ),
    ("POST", "/api/v1/stores/{slug}/delivery-quote/"): Text(
        "Quote delivery",
        "Walks the store's contracted companies by priority and returns the first "
        "zone covering `lat`/`lng`. No coverage is 422.",
    ),
    ("GET", "/api/v1/stores/{slug}/reviews/"): Text(
        "List a store's reviews",
        "The public review wall of one active store.",
    ),
    ("GET", "/api/v1/stores/{slug}/"): Text(
        "Get a store",
        "Detail, opening hours and the delivery companies the store contracts.",
    ),
}


def apply_operation_text(result=None, **kwargs):
    """drf-spectacular postprocessing hook: put the table's text on each operation.

    Anything not in the table is left alone here and caught by the coverage test,
    which is deliberate: a hook that silently invents a title for a new endpoint
    would let the table drift.
    """
    for path, operations in (result or {}).get("paths", {}).items():
        for method, operation in operations.items():
            text = OPERATIONS.get((method.upper(), path))
            if text:
                operation["summary"] = text.summary
                operation["description"] = text.description
    return result
