import os
import stripe
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from config.project_config import (
    STRIPE_SECRET_KEY, APPLE_PRODUCT_PRO, APPLE_PRODUCT_TEAM,
    GOOGLE_PLAY_PRODUCT_PRO, GOOGLE_PLAY_PRODUCT_TEAM,
)
from database import get_db
from models.subscription import Subscription
from models.user import User
from schemas.subscriptions import SubscribeRequest, AppleVerifyRequest, GoogleVerifyRequest
from utils import apple_iap, google_play
from utils.deps import get_current_user
from utils.errors import AppError

stripe.api_key = STRIPE_SECRET_KEY

router = APIRouter()


# Stripe price IDs — set these in env or replace with your actual IDs
_PRICE_IDS = {
    "pro": os.getenv("STRIPE_PRICE_PRO", "price_pro_placeholder"),
    "team": os.getenv("STRIPE_PRICE_TEAM", "price_team_placeholder"),
}

_TRIAL_DAYS = {"pro": 7}

_APPLE_PRODUCT_PLANS = {APPLE_PRODUCT_PRO: "pro", APPLE_PRODUCT_TEAM: "team"}
_GOOGLE_PRODUCT_PLANS = {GOOGLE_PLAY_PRODUCT_PRO: "pro", GOOGLE_PLAY_PRODUCT_TEAM: "team"}


def _subscription_response(sub: Subscription) -> dict:
    return {
        "subscriptionId": str(sub.id),
        "planId": sub.plan_id,
        "status": sub.status,
        "trialEndsAt": sub.trial_ends_at.isoformat() if sub.trial_ends_at else None,
        "currentPeriodEnd": sub.current_period_end.isoformat() if sub.current_period_end else None,
    }


@router.post("")
def subscribe(
    payload: SubscribeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.planId not in ("pro", "team"):
        raise AppError("VALIDATION_ERROR", "planId must be 'pro' or 'team'.", 422)

    price_id = _PRICE_IDS.get(payload.planId)
    if not price_id:
        raise AppError("VALIDATION_ERROR", "Plan not configured.", 422)

    try:
        # Create or retrieve Stripe customer
        existing_sub = db.query(Subscription).filter(Subscription.user_id == current_user.id).first()
        customer_id = existing_sub.stripe_customer_id if existing_sub else None

        if not customer_id:
            customer = stripe.Customer.create(
                email=current_user.email,
                payment_method=payload.paymentMethodId,
                invoice_settings={"default_payment_method": payload.paymentMethodId},
            )
            customer_id = customer.id
        else:
            stripe.PaymentMethod.attach(payload.paymentMethodId, customer=customer_id)
            stripe.Customer.modify(
                customer_id,
                invoice_settings={"default_payment_method": payload.paymentMethodId},
            )

        trial_days = _TRIAL_DAYS.get(payload.planId)
        sub_params: dict = {
            "customer": customer_id,
            "items": [{"price": price_id}],
            "expand": ["latest_invoice.payment_intent"],
        }
        if trial_days:
            sub_params["trial_period_days"] = trial_days

        stripe_sub = stripe.Subscription.create(**sub_params)

    except stripe.error.StripeError as e:
        raise AppError("PAYMENT_ERROR", str(e.user_message), 402)

    # Upsert subscription record
    sub = existing_sub or Subscription(user_id=current_user.id)
    sub.stripe_subscription_id = stripe_sub.id
    sub.stripe_customer_id = customer_id
    sub.plan_id = payload.planId
    sub.status = stripe_sub.status
    sub.trial_ends_at = (
        datetime.fromtimestamp(stripe_sub.trial_end, tz=timezone.utc)
        if stripe_sub.trial_end else None
    )
    sub.current_period_end = datetime.fromtimestamp(
        stripe_sub.current_period_end, tz=timezone.utc
    )

    if not existing_sub:
        db.add(sub)

    current_user.plan = payload.planId
    db.commit()
    db.refresh(sub)

    return _subscription_response(sub)


@router.post("/apple/verify")
def verify_apple_subscription(
    payload: AppleVerifyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        transaction = apple_iap.get_transaction(payload.transactionId)
    except Exception as e:
        raise AppError("PAYMENT_ERROR", f"Could not verify Apple transaction: {e}", 402)

    plan_id = _APPLE_PRODUCT_PLANS.get(transaction.productId)
    if not plan_id:
        raise AppError("VALIDATION_ERROR", "Unrecognized Apple product id.", 422)

    existing_sub = (
        db.query(Subscription)
        .filter(Subscription.apple_original_transaction_id == transaction.originalTransactionId)
        .first()
    )
    sub = existing_sub or Subscription(user_id=current_user.id, platform="apple")
    sub.platform = "apple"
    sub.plan_id = plan_id
    sub.apple_original_transaction_id = transaction.originalTransactionId
    sub.status = apple_iap.status_from_transaction(transaction)
    sub.current_period_end = (
        datetime.fromtimestamp(transaction.expiresDate / 1000, tz=timezone.utc)
        if transaction.expiresDate else None
    )

    if not existing_sub:
        db.add(sub)

    current_user.plan = plan_id
    db.commit()
    db.refresh(sub)

    return _subscription_response(sub)


@router.post("/google/verify")
def verify_google_subscription(
    payload: GoogleVerifyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        purchase = google_play.get_subscription_purchase(payload.purchaseToken)
    except Exception as e:
        raise AppError("PAYMENT_ERROR", f"Could not verify Google Play purchase: {e}", 402)

    item = google_play.line_item(purchase)
    product_id = item.get("productId") if item else payload.productId
    plan_id = _GOOGLE_PRODUCT_PLANS.get(product_id)
    if not plan_id:
        raise AppError("VALIDATION_ERROR", "Unrecognized Google Play product id.", 422)

    existing_sub = (
        db.query(Subscription)
        .filter(Subscription.google_purchase_token == payload.purchaseToken)
        .first()
    )
    sub = existing_sub or Subscription(user_id=current_user.id, platform="google")
    sub.platform = "google"
    sub.plan_id = plan_id
    sub.google_purchase_token = payload.purchaseToken
    sub.status = google_play.status_from_purchase(purchase)
    expiry_time = item.get("expiryTime") if item else None
    sub.current_period_end = (
        datetime.fromisoformat(expiry_time.replace("Z", "+00:00")) if expiry_time else None
    )

    if not existing_sub:
        db.add(sub)

    current_user.plan = plan_id
    db.commit()
    db.refresh(sub)

    return _subscription_response(sub)


@router.delete("/{subscription_id}")
def cancel_subscription(
    subscription_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sub = (
        db.query(Subscription)
        .filter(Subscription.id == subscription_id, Subscription.user_id == current_user.id)
        .first()
    )
    if not sub:
        raise AppError("NOT_FOUND", "Subscription not found.", 404)

    if sub.platform != "stripe":
        raise AppError(
            "VALIDATION_ERROR",
            f"{sub.platform.title()} subscriptions must be cancelled from the "
            f"{'App Store' if sub.platform == 'apple' else 'Play Store'} subscription settings.",
            422,
        )

    try:
        stripe_sub = stripe.Subscription.modify(sub.stripe_subscription_id, cancel_at_period_end=True)
        period_end = datetime.fromtimestamp(stripe_sub.current_period_end, tz=timezone.utc)
    except stripe.error.StripeError as e:
        raise AppError("PAYMENT_ERROR", str(e.user_message), 402)

    sub.status = "cancelled"
    db.commit()

    return {
        "message": f"Subscription cancelled. Access continues until {period_end.isoformat()}."
    }
