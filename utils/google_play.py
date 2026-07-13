from functools import lru_cache

from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account

from config.project_config import GOOGLE_PLAY_PACKAGE_NAME, GOOGLE_PLAY_SERVICE_ACCOUNT_JSON_PATH

_SCOPES = ["https://www.googleapis.com/auth/androidpublisher"]
_BASE_URL = "https://androidpublisher.googleapis.com/androidpublisher/v3"

_STATE_MAP = {
    "SUBSCRIPTION_STATE_ACTIVE": "active",
    "SUBSCRIPTION_STATE_IN_GRACE_PERIOD": "past_due",
    "SUBSCRIPTION_STATE_ON_HOLD": "past_due",
    "SUBSCRIPTION_STATE_CANCELED": "cancelled",
    "SUBSCRIPTION_STATE_PAUSED": "cancelled",
    "SUBSCRIPTION_STATE_EXPIRED": "expired",
}


@lru_cache
def _session() -> AuthorizedSession:
    credentials = service_account.Credentials.from_service_account_file(
        GOOGLE_PLAY_SERVICE_ACCOUNT_JSON_PATH, scopes=_SCOPES,
    )
    return AuthorizedSession(credentials)


def get_subscription_purchase(purchase_token: str) -> dict:
    """Fetches the current state of a Play Billing subscription (subscriptionsv2)."""
    url = f"{_BASE_URL}/applications/{GOOGLE_PLAY_PACKAGE_NAME}/purchases/subscriptionsv2/tokens/{purchase_token}"
    resp = _session().get(url, timeout=10)
    resp.raise_for_status()
    return resp.json()


def status_from_purchase(purchase: dict) -> str:
    return _STATE_MAP.get(purchase.get("subscriptionState"), "active")


def line_item(purchase: dict) -> dict | None:
    items = purchase.get("lineItems") or []
    return items[0] if items else None
