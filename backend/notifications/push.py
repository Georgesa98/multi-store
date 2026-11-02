"""Push transport.

Until FCM credentials exist this only logs: the `Notification` row is the
source of truth and the apps read it over REST, so an unsent push loses
nothing. Swapping in a real provider means changing this module only.
"""

import logging

logger = logging.getLogger(__name__)


def send(notification) -> None:
    tokens = list(
        notification.user.device_tokens.filter(is_active=True).values_list("token", flat=True)
    )
    logger.info(
        "push notification %s to %d device(s) of user %s",
        notification.id,
        len(tokens),
        notification.user_id,
    )
