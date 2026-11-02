"""Websocket URL conf, mounted by `config.asgi`."""

from django.urls import path

from delivery.consumers import TrackingConsumer

websocket_urlpatterns = [
    path("ws/delivery/<uuid:delivery_id>/", TrackingConsumer.as_asgi()),
]
