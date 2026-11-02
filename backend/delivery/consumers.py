"""Read-only tracking socket.

The courier writes its position over HTTP; this consumer only fans those writes
out to whoever is allowed to watch the delivery. Nothing is accepted from the
client, so a forged frame cannot move a marker.
"""

import logging
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from core.enums import Role
from delivery.realtime import group_for
from delivery.tickets import read_ticket

logger = logging.getLogger(__name__)


class TrackingConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.delivery_id = str(self.scope["url_route"]["kwargs"]["delivery_id"])
        claims = self._claims(self._ticket_from_query())
        if claims is None or claims.get("delivery") != self.delivery_id:
            await self.close(code=4401)
            return
        if not await self._may_watch(claims.get("sub")):
            await self.close(code=4403)
            return

        self.group_name = group_for(self.delivery_id)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        group_name = getattr(self, "group_name", None)
        if group_name:
            await self.channel_layer.group_discard(group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        """Clients have nothing to say; location arrives over HTTP."""

    # -- incoming group messages -------------------------------------------

    async def location(self, event):
        await self.send_json(
            {"type": "location", "lat": event["lat"], "lng": event["lng"], "at": event["at"]}
        )

    async def status(self, event):
        await self.send_json({"type": "status", "status": event["status"], "at": event["at"]})

    async def eta(self, event):
        await self.send_json({"type": "eta", "minutes": event["minutes"]})

    # -- ticket and access --------------------------------------------------

    def _ticket_from_query(self) -> str:
        query = parse_qs(self.scope.get("query_string", b"").decode())
        values = query.get("ticket") or []
        return values[0] if values else ""

    @staticmethod
    def _claims(raw):
        if not raw:
            return None
        try:
            return read_ticket(raw)
        except Exception:  # expired, malformed, wrong token type
            return None

    @database_sync_to_async
    def _may_watch(self, user_id) -> bool:
        from django.contrib.auth import get_user_model

        from delivery.models import CompanyMembership, Delivery
        from stores.models import StoreMembership

        if not user_id:
            return False
        try:
            delivery = Delivery.objects.select_related("order").get(pk=self.delivery_id)
        except (Delivery.DoesNotExist, ValueError):
            return False

        user = get_user_model().objects.filter(pk=user_id, is_active=True).first()
        if user is None:
            return False
        if user.role == Role.SUPER_ADMIN:
            return True
        if delivery.order.customer_id == user.id:
            return True
        if delivery.courier_id == user.id:
            return True
        if StoreMembership.objects.filter(
            store_id=delivery.store_id, user=user, is_active=True
        ).exists():
            return True
        if (
            delivery.company_id
            and CompanyMembership.objects.filter(
                company_id=delivery.company_id, user=user, is_active=True
            ).exists()
        ):
            return True
        return False
