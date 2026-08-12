from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from database import get_db
from models.crash_report import CrashReport
from schemas.crash_report import CrashReportRequest
from utils.jwt import decode_access_token

router = APIRouter()


def _optional_user_id(request: Request) -> int | None:
    # Crash reporting must never fail just because auth is broken (a dead
    # token could be *why* the app crashed), so the bearer token here is
    # decoded best-effort rather than required via get_current_user.
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    return decode_access_token(auth.removeprefix("Bearer "))


@router.post("", status_code=201)
def submit_crash_report(
    payload: CrashReportRequest,
    request: Request,
    db: Session = Depends(get_db),
):
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
    db.add(report)
    db.commit()
    db.refresh(report)

    return {"crashReportId": str(report.id)}
