import base64
import json
import logging
import os
import stripe
from datetime import datetime, timezone
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session
from database import get_db
from models.payments import Payment
from models.subscription import Subscription
from utils import apple_iap, google_play

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

@router.post("/stripe")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, os.getenv("STRIPE_WEBHOOK_SECRET")
        )
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Stripe signature")

    if event["type"] == "payment_intent.succeeded":
        intent = event["data"]["object"]

        user_id = intent.metadata.get("user_id")
        order_id = intent.metadata.get("order_id")

        existing = db.query(Payment).filter_by(
            stripe_payment_intent_id=intent.id
        ).first()

        if not existing:
            payment = Payment(
                user_id=int(user_id),
                stripe_payment_intent_id=intent.id,
                amount=intent.amount,
                status=intent.status,
            )
            db.add(payment)
            db.commit()

    return {"status": "ok"}


@router.post("/apple")
async def apple_webhook(request: Request, db: Session = Depends(get_db)):
    """App Store Server Notifications V2. Always ack with 200 — Apple retries
    on non-2xx, and a bad notification here shouldn't create a retry storm."""
    try:
        body = await request.json()
        notification = apple_iap.decode_notification(body["signedPayload"])

        signed_transaction = notification.data.signedTransactionInfo if notification.data else None
        if signed_transaction:
            transaction = apple_iap.decode_transaction(signed_transaction)

            sub = (
                db.query(Subscription)
                .filter(Subscription.apple_original_transaction_id == transaction.originalTransactionId)
                .first()
            )
            if sub:
                sub.status = apple_iap.status_from_notification_type(notification.notificationType, sub.status)
                if transaction.expiresDate:
                    sub.current_period_end = datetime.fromtimestamp(
                        transaction.expiresDate / 1000, tz=timezone.utc
                    )
                db.commit()
    except Exception:
        logger.warning("Apple webhook processing failed", exc_info=True)

    return {"status": "ok"}


@router.post("/google")
async def google_webhook(request: Request, db: Session = Depends(get_db)):
    """Google Play Real-time Developer Notifications (Pub/Sub push). Always ack
    with 200 — Pub/Sub retries on non-2xx, and a bad notification here shouldn't
    create a retry storm."""
    try:
        envelope = await request.json()
        data_b64 = envelope.get("message", {}).get("data")
        if not data_b64:
            return {"status": "ok"}

        payload = json.loads(base64.b64decode(data_b64))
        purchase_token = payload.get("subscriptionNotification", {}).get("purchaseToken")
        if not purchase_token:
            return {"status": "ok"}

        purchase = google_play.get_subscription_purchase(purchase_token)
        item = google_play.line_item(purchase)

        sub = (
            db.query(Subscription)
            .filter(Subscription.google_purchase_token == purchase_token)
            .first()
        )
        if sub:
            sub.status = google_play.status_from_purchase(purchase)
            expiry_time = item.get("expiryTime") if item else None
            if expiry_time:
                sub.current_period_end = datetime.fromisoformat(expiry_time.replace("Z", "+00:00"))
            db.commit()
    except Exception:
        logger.warning("Google Play webhook processing failed", exc_info=True)

    return {"status": "ok"}