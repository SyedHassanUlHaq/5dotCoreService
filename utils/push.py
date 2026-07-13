import logging
import requests

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"

logger = logging.getLogger(__name__)


def send_push(token: str, title: str, body: str, data: dict | None = None) -> None:
    """Send an Expo push notification. Silently logs on failure — never raises."""
    if not token or not token.startswith("ExponentPushToken"):
        return

    payload = {
        "to": token,
        "sound": "default",
        "title": title,
        "body": body,
        "data": data or {},
    }

    try:
        resp = requests.post(EXPO_PUSH_URL, json=payload, timeout=5)
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("Push notification failed: %s", exc)
