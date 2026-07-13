from pydantic import BaseModel


class SubscribeRequest(BaseModel):
    planId: str
    paymentMethodId: str


class AppleVerifyRequest(BaseModel):
    transactionId: str   # from StoreKit 2 after a purchase completes


class GoogleVerifyRequest(BaseModel):
    purchaseToken: str   # from BillingClient after a purchase completes
    productId: str
