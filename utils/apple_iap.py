import os
from datetime import datetime, timezone
from functools import lru_cache

from appstoreserverlibrary.api_client import AppStoreServerAPIClient
from appstoreserverlibrary.models.Environment import Environment
from appstoreserverlibrary.models.JWSTransactionDecodedPayload import JWSTransactionDecodedPayload
from appstoreserverlibrary.models.NotificationTypeV2 import NotificationTypeV2
from appstoreserverlibrary.models.ResponseBodyV2DecodedPayload import ResponseBodyV2DecodedPayload
from appstoreserverlibrary.signed_data_verifier import SignedDataVerifier

from config.project_config import (
    APPLE_CLIENT_ID, APPLE_ENVIRONMENT, APPLE_IAP_KEY_ID,
    APPLE_IAP_PRIVATE_KEY_PATH, APPLE_ISSUER_ID, APPLE_ROOT_CERTS_DIR,
)

_ENVIRONMENT = Environment.PRODUCTION if APPLE_ENVIRONMENT == "Production" else Environment.SANDBOX

# Notification types that change entitlement status; anything not listed here
# (e.g. DID_CHANGE_RENEWAL_STATUS) only toggles auto-renew and leaves the
# existing status alone.
_LAPSED_NOTIFICATIONS = {
    NotificationTypeV2.EXPIRED: "expired",
    NotificationTypeV2.GRACE_PERIOD_EXPIRED: "past_due",
    NotificationTypeV2.DID_FAIL_TO_RENEW: "past_due",
    NotificationTypeV2.REFUND: "cancelled",
    NotificationTypeV2.REVOKE: "cancelled",
}
_RENEWED_NOTIFICATIONS = {NotificationTypeV2.DID_RENEW, NotificationTypeV2.SUBSCRIBED}


@lru_cache
def _signing_key() -> bytes:
    with open(APPLE_IAP_PRIVATE_KEY_PATH, "rb") as f:
        return f.read()


@lru_cache
def _root_certificates() -> list[bytes]:
    certs = []
    for name in sorted(os.listdir(APPLE_ROOT_CERTS_DIR)):
        with open(os.path.join(APPLE_ROOT_CERTS_DIR, name), "rb") as f:
            certs.append(f.read())
    return certs


@lru_cache
def _api_client() -> AppStoreServerAPIClient:
    return AppStoreServerAPIClient(
        _signing_key(), APPLE_IAP_KEY_ID, APPLE_ISSUER_ID, APPLE_CLIENT_ID, _ENVIRONMENT,
    )


@lru_cache
def _verifier() -> SignedDataVerifier:
    return SignedDataVerifier(
        _root_certificates(), enable_online_checks=True,
        environment=_ENVIRONMENT, bundle_id=APPLE_CLIENT_ID,
    )


def get_transaction(transaction_id: str) -> JWSTransactionDecodedPayload:
    """Fetches a transaction from Apple by id and verifies its signature."""
    response = _api_client().get_transaction_info(transaction_id)
    return _verifier().verify_and_decode_signed_transaction(response.signedTransactionInfo)


def decode_transaction(signed_transaction_info: str) -> JWSTransactionDecodedPayload:
    """Verifies a signed transaction JWS already in hand (e.g. from a notification payload)."""
    return _verifier().verify_and_decode_signed_transaction(signed_transaction_info)


def decode_notification(signed_payload: str) -> ResponseBodyV2DecodedPayload:
    """Verifies an App Store Server Notification V2 envelope."""
    return _verifier().verify_and_decode_notification(signed_payload)


def status_from_transaction(transaction: JWSTransactionDecodedPayload) -> str:
    if transaction.revocationDate:
        return "cancelled"
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    if transaction.expiresDate and transaction.expiresDate < now_ms:
        return "expired"
    return "active"


def status_from_notification_type(notification_type: NotificationTypeV2, fallback: str) -> str:
    if notification_type in _LAPSED_NOTIFICATIONS:
        return _LAPSED_NOTIFICATIONS[notification_type]
    if notification_type in _RENEWED_NOTIFICATIONS:
        return "active"
    return fallback
