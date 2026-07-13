import stripe
import os

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

if not stripe.api_key:
    raise RuntimeError("Stripe API key not found. Check STRIPE_SECRET_KEY")
