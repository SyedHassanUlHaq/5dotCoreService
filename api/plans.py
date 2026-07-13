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
            "720p video, 5 min max",
            "Basic plain-English explanations",
            "On-device processing",
        ],
        "maxVideoResolution": "720p",
        "maxVideoDurationSeconds": 300,
        "forensicPdf": False,
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
            "Tamper / cut detection",
            "4K video, 30 min max",
            "Forensic PDF reports",
            "Priority queue · 2× speed",
            "Advanced evidence details",
        ],
        "maxVideoResolution": "4K",
        "maxVideoDurationSeconds": 1800,
        "forensicPdf": True,
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
        "forensicPdf": True,
        "priorityQueue": True,
        "apiAccess": True,
        "apiCallsPerMonth": 10000,
    },
]


@router.get("")
def list_plans():
    return {"plans": _PLANS}
