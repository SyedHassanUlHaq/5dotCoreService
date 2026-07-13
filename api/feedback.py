import uuid
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from models.feedback import Feedback
from models.scan import Scan
from models.user import User
from schemas.feedback import FeedbackRequest
from utils.deps import get_current_user
from utils.errors import AppError

router = APIRouter()


@router.post("", status_code=201)
def submit_feedback(
    payload: FeedbackRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.correctVerdict not in ("authentic", "ai", "unsure"):
        raise AppError("VALIDATION_ERROR", "correctVerdict must be 'authentic', 'ai', or 'unsure'.", 422)

    try:
        scan_uuid = uuid.UUID(payload.scanId)
    except ValueError:
        raise AppError("SCAN_NOT_FOUND", "Invalid scan ID.", 404)

    scan = db.query(Scan).filter(Scan.id == scan_uuid, Scan.user_id == current_user.id).first()
    if not scan:
        raise AppError("SCAN_NOT_FOUND", f"No scan with id {payload.scanId} was found.", 404)

    fb = Feedback(
        scan_id=scan.id,
        user_id=current_user.id,
        correct_verdict=payload.correctVerdict,
        reasons=payload.reasons,
        detail=payload.detail,
        allow_anonymized_copy=payload.allowAnonymizedCopy,
    )
    db.add(fb)
    db.commit()
    db.refresh(fb)

    return {
        "feedbackId": f"fb_{fb.id.hex[:16].upper()}",
        "message": "Thank you. We'll review within 48 hours.",
    }
