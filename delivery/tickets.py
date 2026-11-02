"""Short-lived websocket credentials.

The socket carries no cookies, and a JWT in a query string ends up in logs, so
the ticket is deliberately tiny in scope and time: one delivery, sixty seconds,
no refresh, no other permission.
"""

from datetime import timedelta

from rest_framework_simplejwt.tokens import Token

TICKET_LIFETIME_SECONDS = 60


class TrackingTicket(Token):
    token_type = "tracking"
    lifetime = timedelta(seconds=TICKET_LIFETIME_SECONDS)


def issue_ticket(*, user, delivery) -> str:
    ticket = TrackingTicket()
    ticket["sub"] = str(user.id)
    ticket["delivery"] = str(delivery.id)
    ticket["role"] = user.role
    return str(ticket)


def read_ticket(raw: str) -> TrackingTicket:
    """Verify signature and expiry; raises `TokenError` when the ticket is bad."""
    return TrackingTicket(raw)


def ticket_payload(*, user, delivery) -> dict:
    return {
        "ticket": issue_ticket(user=user, delivery=delivery),
        "expires_in": TICKET_LIFETIME_SECONDS,
        "url": f"/ws/delivery/{delivery.id}/",
    }
