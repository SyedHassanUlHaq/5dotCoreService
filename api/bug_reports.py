from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from models.bug_report import BugReport
from models.user import User
from schemas.bug_report import BugReportRequest
from utils.deps import get_current_user
from utils.errors import AppError

router = APIRouter()

SEVERITIES = ("low", "medium", "high", "critical")


def _bug_report_response(report: BugReport) -> dict:
    return {
        "bugReportId": str(report.id),
        "status": report.status,
        "createdAt": report.created_at.isoformat() if report.created_at else None,
    }


@router.post("", status_code=201)
def submit_bug_report(
    payload: BugReportRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.severity is not None and payload.severity not in SEVERITIES:
        raise AppError("VALIDATION_ERROR", f"severity must be one of {', '.join(SEVERITIES)}.", 422)

    report = BugReport(
        user_id=current_user.id,
        title=payload.title,
        description=payload.description,
        steps_to_reproduce=payload.stepsToReproduce,
        severity=payload.severity,
        platform=payload.platform,
        app_version=payload.appVersion,
        os_version=payload.osVersion,
        device_model=payload.deviceModel,
        context=payload.context,
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    return _bug_report_response(report)


@router.get("")
def list_my_bug_reports(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    reports = (
        db.query(BugReport)
        .filter(BugReport.user_id == current_user.id)
        .order_by(BugReport.created_at.desc())
        .all()
    )
    return {"items": [_bug_report_response(r) for r in reports]}
