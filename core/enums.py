"""Every enum in the system, in one importable place.

Keeping them outside app modules avoids circular imports between apps that
need the same vocabulary (a store query needs `Role`, an order needs
`DeliveryStatus`, and so on).
"""

from django.db import models


class Role(models.TextChoices):
    SUPER_ADMIN = "super_admin", "Super admin"
    STORE_ADMIN = "store_admin", "Store admin"
    STORE_STAFF = "store_staff", "Store staff"
    DELIVERY_ADMIN = "delivery_admin", "Delivery company admin"
    DELIVERY_STAFF = "delivery_staff", "Delivery company staff"
    COURIER = "courier", "Courier"
    CUSTOMER = "customer", "Customer"


class StoreStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"
    CLOSED = "closed", "Closed"


class CompanyStatus(models.TextChoices):
    """Same lifecycle as a store, but for a delivery company."""

    PENDING = "pending", "Pending"
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"
    CLOSED = "closed", "Closed"


class MemberRole(models.TextChoices):
    OWNER = "owner", "Owner"
    MANAGER = "manager", "Manager"
    STAFF = "staff", "Staff"


class ProductStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    ACTIVE = "active", "Active"
    ARCHIVED = "archived", "Archived"


class OrderStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    CONFIRMED = "confirmed", "Confirmed"
    PREPARING = "preparing", "Preparing"
    READY = "ready", "Ready"
    ASSIGNED = "assigned", "Assigned"
    OUT_FOR_DELIVERY = "out_for_delivery", "Out for delivery"
    DELIVERED = "delivered", "Delivered"
    CANCELLED = "cancelled", "Cancelled"
    REFUNDED = "refunded", "Refunded"


class PaymentStatus(models.TextChoices):
    UNPAID = "unpaid", "Unpaid"
    COLLECTED = "collected", "Collected"
    WAIVED = "waived", "Waived"


class DeliveryStatus(models.TextChoices):
    UNASSIGNED = "unassigned", "Unassigned"
    REQUESTED = "requested", "Requested from the company"
    OFFERED = "offered", "Offered"
    ACCEPTED = "accepted", "Accepted"
    PICKED_UP = "picked_up", "Picked up"
    DELIVERED = "delivered", "Delivered"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


class DeliveryAction(models.TextChoices):
    REQUESTED = "requested", "Requested from the company"
    ASSIGNED = "assigned", "Assigned"
    REASSIGNED = "reassigned", "Reassigned"
    RELEASED = "released", "Released"
    ACCEPTED = "accepted", "Accepted"
    DECLINED = "declined", "Declined"
    PICKED_UP = "picked_up", "Picked up"
    DELIVERED = "delivered", "Delivered"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


class InventoryReason(models.TextChoices):
    RESTOCK = "restock", "Restock"
    SALE = "sale", "Sale"
    CANCEL_RETURN = "cancel_return", "Cancel return"
    MANUAL = "manual", "Manual"
    DAMAGE = "damage", "Damage"


class CouponType(models.TextChoices):
    PERCENT = "percent", "Percent"
    FIXED = "fixed", "Fixed"


class LedgerKind(models.TextChoices):
    SALE = "sale", "Sale"
    REFUND = "refund", "Refund"
    COMMISSION = "commission", "Commission"
    PAYOUT = "payout", "Payout"


class NotificationType(models.TextChoices):
    ORDER_UPDATE = "order_update", "Order update"
    ASSIGNMENT = "assignment", "Assignment"
    PAYMENT = "payment", "Payment"
    SYSTEM = "system", "System"


class DevicePlatform(models.TextChoices):
    IOS = "ios", "iOS"
    ANDROID = "android", "Android"
    WEB = "web", "Web"


class Vehicle(models.TextChoices):
    MOTORCYCLE = "motorcycle", "Motorcycle"
    CAR = "car", "Car"
    BICYCLE = "bicycle", "Bicycle"
    ON_FOOT = "on_foot", "On foot"
