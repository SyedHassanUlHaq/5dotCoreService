from fastapi import APIRouter

router = APIRouter()

_PLANS = [
    {
        "id": "free",
        "name": "Free",
        "price": 0,
        "currency": "USD",
        "billingPeriod": "forever",
        "scansPerMonth": 50,
        "features": [
            "Audio + video AI detection",
            "Up to 125 MB per file",
            "Basic plain-English explanations",
        ],
        "priorityQueue": False,
        "apiAccess": False,
    },
    {
        "id": "pro",
        "name": "Pro",
        "price": 9,
        "currency": "USD",
        "billingPeriod": "month",
        "scansPerMonth": 500,
        "features": [
            "Lip-sync detection",
            "Up to 125 MB per file",
            "Priority queue · 2× speed",
            "Advanced evidence details",
        ],
        "priorityQueue": True,
        "apiAccess": False,
        "trialDays": 7,
    },
    {
        "id": "team",
        "name": "Team",
        "price": 24,
        "currency": "USD",
        "billingPeriod": "month",
        "scansPerMonth": None,
        "seats": 5,
        "features": [
            "5 seats included",
            "API access · 10k calls/mo",
            "SSO + audit log",
            "Dedicated model tuning",
            "Priority support",
        ],
        "priorityQueue": True,
        "apiAccess": True,
        "apiCallsPerMonth": 10000,
    },
]


@router.get("")
def list_plans():
    return {"plans": _PLANS}
