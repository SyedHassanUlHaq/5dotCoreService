from fastapi import APIRouter
import stripe
from schemas.schemas import PaymentIntentCreate
from utils.errors import AppError

router = APIRouter(prefix="/payments", tags=["Payments"])

@router.post("/create-payment-intent")
def create_payment_intent(payload: PaymentIntentCreate):
    if payload.amount <= 0:
        raise AppError("VALIDATION_ERROR", "amount must be greater than 0.", 422)

    try:
        intent = stripe.PaymentIntent.create(
            amount=payload.amount,
            currency="usd",
            automatic_payment_methods={"enabled": True},
            metadata={
                "user_id": payload.user_id,
                "order_id": payload.order_id
            }
        )
        return {"client_secret": intent.client_secret}
    except stripe.error.StripeError as e:
        raise AppError("PAYMENT_ERROR", str(e.user_message), 402)