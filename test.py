"""
Smoke test for core_service.

Run from inside core_service/ (so local packages resolve the same way they
do for `uvicorn main:app`):

    cd core_service
    python test.py

Checks are split into two tiers:
  - HARD checks: pure code/wiring correctness (imports, route mounting,
    JWT error handling). No
    network/GPU/live DB required — these must pass.
  - SOFT checks: anything that touches the outside world (a live
    DATABASE_URL, STRIPE_SECRET_KEY). These are reported but don't fail the
    run, since a missing DB connection or unset Stripe key isn't a bug in
    this service's code.
"""

import sys
import traceback

from api import detection_request


PASS = "[PASS]"
FAIL = "[FAIL]"
WARN = "[WARN]"

hard_failures: list[str] = []
soft_warnings: list[str] = []


def _run(label: str, fn, hard: bool = True):
    try:
        fn()
        print(f"{PASS} {label}")
        return True
    except Exception as exc:
        bucket = hard_failures if hard else soft_warnings
        bucket.append(f"{label}: {exc}")
        print(f"{FAIL if hard else WARN} {label}: {exc}")
        if hard:
            traceback.print_exc(limit=3)
        return False


# ---------------------------------------------------------------------------
# HARD checks — no network, no GPU, no live DB
# ---------------------------------------------------------------------------

def check_config_imports():
    from config.project_config import (  # noqa: F401
        DATABASE_URL, SECRET_KEY, ALGORITHM,
        MODEL_VERSION, PLAN_SCAN_LIMITS, STRIPE_SECRET_KEY,
    )


def check_database_module_imports():
    from database import Base, SessionLocal, engine, get_db  # noqa: F401


def check_models_import():
    from models import User, Payment, RefreshToken, Scan, Feedback, Subscription  # noqa: F401


def check_schemas_import():
    from schemas import (  # noqa: F401
        UserCreate, UserResponse, UserLogin, Token,
        OTPRequest, OTPVerify, ResetPasswordRequest, ResetPasswordVerify,
        PaymentIntentCreate,
    )
    from schemas.auth import SignUpRequest, SignInRequest, RefreshRequest  # noqa: F401
    from schemas.feedback import FeedbackRequest  # noqa: F401
    from schemas.scans import UrlScanRequest  # noqa: F401
    from schemas.subscriptions import SubscribeRequest, AppleVerifyRequest, GoogleVerifyRequest  # noqa: F401
    from schemas.users import UpdateProfileRequest  # noqa: F401


def check_utils_import():
    from utils.errors import AppError  # noqa: F401
    from utils.s3 import upload_file, download_file, delete_file, presigned_url  # noqa: F401
    from utils.push import send_push  # noqa: F401
    from utils.deps import get_current_user  # noqa: F401
    from utils.apple_iap import get_transaction, decode_notification, status_from_transaction  # noqa: F401
    from utils.google_play import get_subscription_purchase, status_from_purchase, line_item  # noqa: F401
    from utils import (  # noqa: F401
        create_access_token, send_otp_email, generate_otp,
        hash_password, verify_password, store_otp, verify_otp, delete_otp,
    )


def check_api_routers_import():
    from api import auth, users, feedback, plans, stats, subscriptions, webhooks, payments
    for name, mod in {
        "auth": auth, "users": users, "feedback": feedback, "plans": plans,
        "scans": detection_request, "stats": stats, "subscriptions": subscriptions,
        "webhooks": webhooks, "payments": payments,
    }.items():
        assert hasattr(mod, "router"), f"api.{name} has no `router`"


def check_fastapi_app_builds():
    import main
    assert main.app is not None
    route_paths = {r.path for r in main.app.routes}

    expected = {
        "/",
        "/v1/auth/signup", "/v1/auth/signin",
        "/v1/users/me",
        "/v1/scans", "/v1/scans/{scan_id}",
        "/v1/feedback",
        "/v1/plans",
        "/v1/subscriptions",
        "/v1/stats/weekly",
        # NOTE: webhooks.router already carries prefix="/webhooks" itself,
        # and main.py mounts it under an *additional* "/v1/webhooks" prefix —
        # a pre-existing quirk from the original monolith, intentionally
        # preserved here rather than silently "fixed". This assertion pins
        # the current (quirky) behavior so a future change is a deliberate
        # decision, not an accidental regression.
        "/v1/webhooks/webhooks/stripe",
        "/v1/payments/create-payment-intent",
    }
    missing = expected - route_paths
    assert not missing, f"missing routes: {missing}"


def check_plans_endpoint():
    from fastapi.testclient import TestClient
    import main
    client = TestClient(main.app)
    resp = client.get("/v1/plans")
    assert resp.status_code == 200, resp.text
    plans = resp.json()["plans"]
    assert {p["id"] for p in plans} == {"free", "pro", "team"}


def check_root_endpoint():
    from fastapi.testclient import TestClient
    import main
    client = TestClient(main.app)
    resp = client.get("/")
    assert resp.status_code == 200, resp.text
    assert resp.json()["message"] == "5dot Core API running"


def check_auth_error_handling():
    """
    Exercises get_current_user's failure path (bad JWT) end-to-end through
    the AppError exception handler — no DB hit needed, since decoding fails
    before any query runs. Confirms the handler is wired and returns the
    expected structured error shape.
    """
    from fastapi.testclient import TestClient
    import main
    client = TestClient(main.app)
    resp = client.get("/v1/users/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401, resp.text
    body = resp.json()
    assert body["error"]["code"] == "UNAUTHORIZED", body


# ---------------------------------------------------------------------------
# SOFT checks — touch the network / a real database / Stripe config
# ---------------------------------------------------------------------------

def check_database_connection():
    from sqlalchemy import text
    from database import engine
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))


def check_stripe_config_module():
    """config/stripe.py intentionally raises if STRIPE_SECRET_KEY is unset — that's by design, not a bug."""
    import config.stripe  # noqa: F401


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main_test() -> int:
    print("=== core_service smoke test ===\n")

    print("-- hard checks (imports & wiring, no network/DB required) --")
    _run("config.project_config imports", check_config_imports)
    _run("database module imports", check_database_module_imports)
    _run("models (User, Payment, RefreshToken, Scan, Feedback, Subscription) import", check_models_import)
    _run("schemas import", check_schemas_import)
    _run("utils (errors, s3, push, deps, jwt, security, otp_store, email) import", check_utils_import)
    _run("api routers import", check_api_routers_import)
    _run("FastAPI app builds + routes mounted", check_fastapi_app_builds)
    _run("GET /v1/plans", check_plans_endpoint)
    _run("GET /", check_root_endpoint)
    _run("GET /v1/users/me with bad JWT -> 401 AppError shape", check_auth_error_handling)

    print("\n-- soft checks (network / database / stripe key required) --")
    _run("database connection (SELECT 1)", check_database_connection, hard=False)
    _run("config.stripe module (needs STRIPE_SECRET_KEY)", check_stripe_config_module, hard=False)

    print("\n=== summary ===")
    if hard_failures:
        print(f"{FAIL} {len(hard_failures)} hard check(s) failed:")
        for f in hard_failures:
            print(f"  - {f}")
    else:
        print(f"{PASS} all hard checks passed")

    if soft_warnings:
        print(f"{WARN} {len(soft_warnings)} soft check(s) skipped/failed (network/DB/config not available):")
        for w in soft_warnings:
            print(f"  - {w}")

    return 1 if hard_failures else 0


if __name__ == "__main__":
    sys.exit(main_test())
