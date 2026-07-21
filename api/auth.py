import hashlib
import hmac
import os
import random
import string
from datetime import datetime, timezone

import requests as http_requests
from fastapi import APIRouter, Depends
from jose import jwt as jose_jwt, JWTError
from sqlalchemy.orm import Session

from config.project_config import (
    GOOGLE_CLIENT_ID, APPLE_CLIENT_ID, ALGORITHM,
    FACEBOOK_APP_SECRET, MICROSOFT_CLIENT_ID, MICROSOFT_TENANT_ID,
)
from schemas.auth import (
    SignUpRequest, VerifySignUpRequest, SignInRequest, GoogleAuthRequest,
    AppleAuthRequest, FacebookAuthRequest, OutlookAuthRequest,
    RefreshRequest, ForgotPasswordRequest, ResetPasswordRequest,
)
from database import get_db
from models.refresh_token import RefreshToken
from models.user import User
from utils.email import send_otp_email, generate_otp
from utils.errors import AppError
from utils.jwt import create_access_token, create_refresh_token, hash_refresh_token
from utils.otp_store import store_otp, verify_otp, delete_otp
from utils.security import hash_password, verify_password

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user_response(user: User) -> dict:
    from config.project_config import MODEL_VERSION, PLAN_SCAN_LIMITS
    import calendar
    now = datetime.now(timezone.utc)
    last_day = calendar.monthrange(now.year, now.month)[1]
    reset_date = now.replace(day=last_day, hour=23, minute=59, second=59, microsecond=0)

    display_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or user.name or user.email
    initials = "".join(w[0].upper() for w in display_name.split()[:2]) if display_name else "?"

    return {
        "id": f"usr_{user.id}",
        "email": user.email,
        "name": display_name,
        "firstName": user.first_name,
        "lastName": user.last_name,
        "phoneNumber": user.phone_number,
        "avatarInitials": initials,
        "avatarColor": user.avatar_color or "#E91E8C",
        "plan": user.plan,
        "modelVersion": MODEL_VERSION,
        "scansUsedThisMonth": user.scans_used_this_month,
        "scansLimitThisMonth": PLAN_SCAN_LIMITS.get(user.plan),
        "planResetDate": reset_date.isoformat(),
        "accuracyRate": user.accuracy_rate,
        "createdAt": user.created_at.isoformat() if user.created_at else now.isoformat(),
    }


def _issue_tokens(user: User, db: Session) -> dict:
    access = create_access_token(user.id)
    raw_refresh, hashed, expires_at = create_refresh_token()

    db.add(RefreshToken(
        user_id=user.id,
        token_hash=hashed,
        expires_at=expires_at,
    ))
    db.commit()

    return {
        "accessToken": access,
        "refreshToken": raw_refresh,
        "user": _user_response(user),
    }


def _get_or_create_oauth_user(db: Session, email: str, name: str | None) -> User:
    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(email=email, name=name, hashed_password=None)
        db.add(user)
        db.commit()
        db.refresh(user)
    elif name and not user.name:
        user.name = name
        db.commit()
    return user


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/signup", status_code=202)
async def signup(payload: SignUpRequest, db: Session = Depends(get_db)):
    if len(payload.password) < 8:
        raise AppError("VALIDATION_ERROR", "Password must be at least 8 characters.", 422)
    if db.query(User).filter(User.email == payload.email).first():
        raise AppError("EMAIL_IN_USE", "An account with this email already exists.", 409)

    # Account isn't created yet, the OTP payload carries everything needed to
    # create it once verified, so an unverified signup never leaves a row behind.
    otp = generate_otp()
    store_otp(payload.email, otp, {
        "email": payload.email,
        "hashedPassword": hash_password(payload.password),
        "firstName": payload.firstName,
        "lastName": payload.lastName,
        "phoneNumber": payload.phoneNumber,
    })
    await send_otp_email(payload.email, otp)
    return {"message": "Verification code sent.", "email": payload.email}


@router.post("/signup/verify", status_code=201)
def verify_signup(payload: VerifySignUpRequest, db: Session = Depends(get_db)):
    valid, data = verify_otp(payload.email, payload.otp)
    if not valid:
        raise AppError("UNAUTHORIZED", "Invalid or expired code.", 401)

    if db.query(User).filter(User.email == payload.email).first():
        delete_otp(payload.email)
        raise AppError("EMAIL_IN_USE", "An account with this email already exists.", 409)

    user = User(
        email=data["email"],
        hashed_password=data["hashedPassword"],
        first_name=data["firstName"],
        last_name=data["lastName"],
        phone_number=data["phoneNumber"],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    delete_otp(payload.email)
    return _issue_tokens(user, db)


@router.post("/signin")
def signin(payload: SignInRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not user.hashed_password or not verify_password(payload.password, user.hashed_password):
        raise AppError("UNAUTHORIZED", "Invalid email or password.", 401)
    return _issue_tokens(user, db)


@router.post("/google")
def google_auth(payload: GoogleAuthRequest, db: Session = Depends(get_db)):
    try:
        from google.oauth2 import id_token
        from google.auth.transport import requests as google_requests
        info = id_token.verify_oauth2_token(payload.idToken, google_requests.Request(), GOOGLE_CLIENT_ID)
    except Exception as e:
        raise AppError("UNAUTHORIZED", f"Invalid Google token: {e}", 401)

    email = info.get("email")
    if not email:
        raise AppError("UNAUTHORIZED", "Google token did not include an email.", 401)

    given = info.get("given_name", "")
    family = info.get("family_name", "")
    name = f"{given} {family}".strip() or None

    user = _get_or_create_oauth_user(db, email, name)
    return _issue_tokens(user, db)


@router.post("/apple")
def apple_auth(payload: AppleAuthRequest, db: Session = Depends(get_db)):
    try:
        # Fetch Apple JWKS
        jwks_resp = http_requests.get("https://appleid.apple.com/auth/keys", timeout=5)
        jwks = jwks_resp.json()

        header = jose_jwt.get_unverified_header(payload.identityToken)
        key = next((k for k in jwks["keys"] if k["kid"] == header.get("kid")), None)
        if not key:
            raise ValueError("Matching Apple public key not found.")

        info = jose_jwt.decode(
            payload.identityToken,
            key,
            algorithms=["RS256"],
            audience=APPLE_CLIENT_ID,
            options={"verify_at_hash": False},
        )
    except Exception as e:
        raise AppError("UNAUTHORIZED", f"Invalid Apple token: {e}", 401)

    email = info.get("email")
    if not email:
        raise AppError("UNAUTHORIZED", "Apple token did not include an email.", 401)

    full_name = payload.fullName or {}
    given = full_name.get("givenName", "")
    family = full_name.get("familyName", "")
    name = f"{given} {family}".strip() or None

    user = _get_or_create_oauth_user(db, email, name)
    return _issue_tokens(user, db)


@router.post("/facebook")
def facebook_auth(payload: FacebookAuthRequest, db: Session = Depends(get_db)):
    if not FACEBOOK_APP_SECRET:
        raise AppError("SERVER_ERROR", "Facebook auth is not configured.", 500)

    # appsecret_proof ties the call to our app secret, so Facebook rejects
    # tokens that weren't issued for this app.
    proof = hmac.new(
        FACEBOOK_APP_SECRET.encode(), payload.accessToken.encode(), hashlib.sha256
    ).hexdigest()

    try:
        resp = http_requests.get(
            "https://graph.facebook.com/me",
            params={
                "fields": "id,name,email,first_name,last_name",
                "access_token": payload.accessToken,
                "appsecret_proof": proof,
            },
            timeout=5,
        )
        info = resp.json()
        if "error" in info:
            raise ValueError(info["error"].get("message", "Facebook rejected the token."))
    except Exception as e:
        raise AppError("UNAUTHORIZED", f"Invalid Facebook token: {e}", 401)

    email = info.get("email")
    if not email:
        raise AppError("UNAUTHORIZED", "Facebook token did not include an email.", 401)

    given = info.get("first_name", "")
    family = info.get("last_name", "")
    name = f"{given} {family}".strip() or info.get("name")

    user = _get_or_create_oauth_user(db, email, name)
    return _issue_tokens(user, db)


@router.post("/outlook")
def outlook_auth(payload: OutlookAuthRequest, db: Session = Depends(get_db)):
    try:
        # Fetch Microsoft identity platform JWKS
        jwks_resp = http_requests.get(
            f"https://login.microsoftonline.com/{MICROSOFT_TENANT_ID}/discovery/v2.0/keys", timeout=5
        )
        jwks = jwks_resp.json()

        header = jose_jwt.get_unverified_header(payload.idToken)
        key = next((k for k in jwks["keys"] if k["kid"] == header.get("kid")), None)
        if not key:
            raise ValueError("Matching Microsoft public key not found.")

        info = jose_jwt.decode(
            payload.idToken,
            key,
            algorithms=["RS256"],
            audience=MICROSOFT_CLIENT_ID,
            options={"verify_at_hash": False},
        )
    except Exception as e:
        raise AppError("UNAUTHORIZED", f"Invalid Outlook token: {e}", 401)

    email = info.get("email") or info.get("preferred_username")
    if not email:
        raise AppError("UNAUTHORIZED", "Outlook token did not include an email.", 401)

    user = _get_or_create_oauth_user(db, email, info.get("name"))
    return _issue_tokens(user, db)


@router.post("/refresh")
def refresh_token(payload: RefreshRequest, db: Session = Depends(get_db)):
    hashed = hash_refresh_token(payload.refreshToken)
    token_row = (
        db.query(RefreshToken)
        .filter(RefreshToken.token_hash == hashed, RefreshToken.revoked == False)
        .first()
    )
    if not token_row or token_row.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise AppError("UNAUTHORIZED", "Refresh token is invalid or expired.", 401)

    # Rotate: revoke old, issue new
    token_row.revoked = True
    db.commit()

    user = db.query(User).filter(User.id == token_row.user_id).first()
    access = create_access_token(user.id)
    raw_refresh, hashed_new, expires_at = create_refresh_token()

    db.add(RefreshToken(user_id=user.id, token_hash=hashed_new, expires_at=expires_at))
    db.commit()

    return {"accessToken": access, "refreshToken": raw_refresh}


@router.post("/signout", status_code=204)
def signout(payload: RefreshRequest, db: Session = Depends(get_db)):
    hashed = hash_refresh_token(payload.refreshToken)
    token_row = db.query(RefreshToken).filter(RefreshToken.token_hash == hashed).first()
    if token_row:
        token_row.revoked = True
        db.commit()
    return None


@router.post("/forgot-password")
async def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if user:
        otp = generate_otp()
        store_otp(payload.email, otp, {"email": payload.email})
        await send_otp_email(payload.email, otp)
    # Always return the same message to avoid email enumeration
    return {"message": "Reset email sent if account exists."}


@router.post("/reset-password")
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    if len(payload.newPassword) < 8:
        raise AppError("VALIDATION_ERROR", "Password must be at least 8 characters.", 422)

    valid, _ = verify_otp(payload.email, payload.otp)
    if not valid:
        raise AppError("UNAUTHORIZED", "Invalid or expired OTP.", 401)

    user = db.query(User).filter(User.email == payload.email).first()
    if not user:
        raise AppError("UNAUTHORIZED", "User not found.", 401)

    user.hashed_password = hash_password(payload.newPassword)
    db.commit()
    delete_otp(payload.email)
    return {"message": "Password reset successfully."}
