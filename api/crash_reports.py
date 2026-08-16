import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from database import get_db
from models.crash_report import CrashReport
from schemas.crash_report import CrashReportRequest
from utils.jwt import decode_access_token

logger = logging.getLogger(__name__)

router = APIRouter()


def _optional_user_id(request: Request) -> int | None:
    # Crash reporting must never fail just because auth is broken (a dead
    # token could be *why* the app crashed), so the bearer token here is
    # decoded best-effort rather than required via get_current_user.
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    try:
        return decode_access_token(auth.removeprefix("Bearer "))
    except Exception:
        return None


@router.post("", status_code=201)
def submit_crash_report(
    payload: CrashReportRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    # Same reasoning as the auth handling above: a crash reporter that can
    # itself fail (DB hiccup, etc.) just adds a second failure on top of the
    # one the client is already trying to report, so this never raises —
    # it best-effort persists and always acks the client.
    report = CrashReport(
        user_id=_optional_user_id(request),
        message=payload.message,
        stack_trace=payload.stackTrace,
        is_fatal=payload.isFatal,
        platform=payload.platform,
        app_version=payload.appVersion,
        os_version=payload.osVersion,
        device_model=payload.deviceModel,
        context=payload.context,
    )
    try:
        db.add(report)
        db.commit()
        db.refresh(report)
    except Exception:
        logger.error("Failed to persist crash report", exc_info=True)
        db.rollback()
        return {"crashReportId": None}

    return {"crashReportId": str(report.id)}
