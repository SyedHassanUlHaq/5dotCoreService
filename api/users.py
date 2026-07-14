import calendar
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from config.project_config import MODEL_VERSION, PLAN_SCAN_LIMITS
from database import get_db
from models.user import User
from schemas.users import UpdateProfileRequest
from utils.deps import get_current_user
from utils.errors import AppError

router = APIRouter()


def _user_response(user: User) -> dict:
    now = datetime.now(timezone.utc)
    last_day = calendar.monthrange(now.year, now.month)[1]
    reset_date = now.replace(day=last_day, hour=23, minute=59, second=59, microsecond=0)

    display_name = user.name or f"{user.first_name or ''} {user.last_name or ''}".strip() or user.email
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


@router.get("/me")
def get_me(current_user: User = Depends(get_current_user)):
    return _user_response(current_user)


@router.patch("/me")
def update_me(
    payload: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.name is not None:
        current_user.name = payload.name
    if payload.avatarColor is not None:
        current_user.avatar_color = payload.avatarColor
    if payload.pushToken is not None:
        current_user.push_token = payload.pushToken
    if payload.firstName is not None:
        current_user.first_name = payload.firstName
    if payload.lastName is not None:
        current_user.last_name = payload.lastName
    if payload.phoneNumber is not None:
        current_user.phone_number = payload.phoneNumber
    db.commit()
    db.refresh(current_user)
    return _user_response(current_user)
