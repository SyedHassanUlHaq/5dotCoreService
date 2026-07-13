from fastapi import APIRouter, HTTPException
import stripe
from schemas.schemas import PaymentIntentCreate

router = APIRouter(prefix="/payments", tags=["Payments"])

@router.post("/create-payment-intent")
def create_payment_intent(payload: PaymentIntentCreate):
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
        raise HTTPException(status_code=400, detail=e.user_message)