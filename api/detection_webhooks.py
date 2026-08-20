"""
Called by the downstream AI service repos to signal that a detection job
finished. Each route corresponds to one detection type; once every type the
user requested for that DetectionRequest has reached a terminal state, the
overall request is marked done and the user is notified.

  POST /video-trigger     -> ai_video
  POST /audio_trigger     -> ai_audio
  POST /lipsync_trigger   -> lipsync
"""

import logging
import os
import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from api.detection_request import STATUS_FIELD_BY_TYPE, _requested_types_of
from config.project_config import DEFAULT_DETECTION_THRESHOLD
from database import get_db
from models.chunk import Chunk
from models.detection_request import DetectionRequest
from models.notification import Notification
from schemas.detection_webhooks import DetectionWebhookPayload
from utils.errors import AppError
from utils.notification_templates import NOTIFICATION_TEMPLATES
from utils.push import send_push

logger = logging.getLogger(__name__)

router = APIRouter()

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

# Same mapping as utils/pdf_report.py's CHUNK_SCORE_FIELD — kept as a
# separate copy since it's a different module's concern, but the lipsync
# entry must stay in sync: it reads through the normalized property since
# that worker writes its per-chunk score on a 0-100 scale, not 0-1.
CHUNK_RESULT_FIELD = {
    "ai_audio": "ai_audio_score",
    "ai_video": "ai_video_score",
    "lipsync": "lipsync_score_normalized",
}


def _derive_result_from_chunks(db: Session, dr: DetectionRequest, detection_type: str) -> dict | None:
    """Fallback for a worker whose completion webhook includes no `result`
    payload at all (confirmed happening for every real lipsync scan so far —
    its webhook only ever signals bare completion). The per-chunk scores it
    already wrote to detection_chunks are still real, so build a result from
    those instead of showing nothing.

    Uses the peak (max) segment score, not an average: for a forensic flag,
    one strong incriminating segment should drive the verdict, not get
    diluted by a long clean stretch either side of it.
    """
    field = CHUNK_RESULT_FIELD.get(detection_type)
    if not field:
        return None
    chunks = db.query(Chunk).filter(Chunk.detection_request_id == dr.id).all()
    scores = [v for c in chunks if (v := getattr(c, field, None)) is not None]
    if not scores:
        return None
    return {"score": max(scores), "threshold": DEFAULT_DETECTION_THRESHOLD.get(detection_type, 0.5)}


def _set_result(dr: DetectionRequest, detection_type: str, result: dict):
    """result_data is a plain JSONB column (no MutableDict tracking), so
    mutating the existing dict in place and reassigning it is a no-op as far
    as SQLAlchemy's change-tracking is concerned — the attribute's identity
    never changes, so the write silently never reaches the database. This
    was confirmed to bite every multi-type scan: whichever detection type's
    webhook landed first persisted fine (result_data was still None, so the
    assignment really was a new object), and every type after it was
    silently dropped. flag_modified forces SQLAlchemy to write it anyway.
    """
    result_data = dr.result_data or {}
    result_data[detection_type] = result
    dr.result_data = result_data
    flag_modified(dr, "result_data")


def _verify_secret(x_webhook_secret: str | None = Header(None)):
    if WEBHOOK_SECRET and (not x_webhook_secret or not secrets.compare_digest(x_webhook_secret, WEBHOOK_SECRET)):
        raise AppError("UNAUTHORIZED", "Invalid webhook secret.", 401)


def _notify_user(db: Session, dr: DetectionRequest):
    user = dr.user
    if not user:
        return

    template_key = "detection_failed" if dr.status == "failed" else "detection_complete"
    template = NOTIFICATION_TEMPLATES[template_key]
    title = template["title"].format(filename=dr.filename)
    body = template["body"].format(filename=dr.filename)

    notification = Notification(
        user_id=user.id,
        template=template_key,
        title=title,
        body=body,
        data={"requestId": str(dr.id)},
    )
    db.add(notification)
    db.commit()

    if user.push_token:
        send_push(user.push_token, title, body, data={"requestId": str(dr.id), "template": template_key})


def _handle_completion(detection_type: str, payload: DetectionWebhookPayload, db: Session) -> dict:
    try:
        rid = uuid.UUID(payload.job_id)
    except ValueError:
        raise AppError("NOT_FOUND", f"No detection request with id {payload.job_id} was found.", 404)

    dr = db.query(DetectionRequest).filter(DetectionRequest.id == rid).first()
    if not dr:
        raise AppError("NOT_FOUND", f"No detection request with id {payload.job_id} was found.", 404)

    failed = payload.status.lower() in ("failed", "error")
    setattr(dr, STATUS_FIELD_BY_TYPE[detection_type], "failed" if failed else "complete")

    if payload.result:
        result = dict(payload.result)
        if "score" in result and "threshold" not in result:
            default = DEFAULT_DETECTION_THRESHOLD.get(detection_type, 0.5)
            logger.warning(
                "Webhook for %s (%s) sent a score with no threshold — backfilling default %.2f. "
                "This worker's payload is missing a field the others send; worth fixing upstream.",
                payload.job_id, detection_type, default,
            )
            result["threshold"] = default

        _set_result(dr, detection_type, result)
    elif not failed:
        derived = _derive_result_from_chunks(db, dr, detection_type)
        if derived:
            logger.warning(
                "Webhook for %s (%s) completed with no result payload at all — "
                "deriving a score of %.2f from its scored chunks instead. "
                "This worker's payload is missing the result entirely; worth fixing upstream.",
                payload.job_id, detection_type, derived["score"],
            )
            _set_result(dr, detection_type, derived)

    if failed:
        note = f"{detection_type} failed"
        dr.error_message = f"{dr.error_message}; {note}" if dr.error_message else note

    db.commit()
    db.refresh(dr)

    requested_types = _requested_types_of(dr)
    still_pending = any(
        getattr(dr, STATUS_FIELD_BY_TYPE[t]) not in ("complete", "failed")
        for t in requested_types
    )
    if still_pending:
        return {"status": "ok"}

    any_failed = any(getattr(dr, STATUS_FIELD_BY_TYPE[t]) == "failed" for t in requested_types)
    dr.status = "failed" if any_failed else "complete"
    dr.completed_at = datetime.now(timezone.utc)
    db.commit()

    _notify_user(db, dr)

    return {"status": "ok"}


@router.post("/video-trigger", dependencies=[Depends(_verify_secret)])
def video_trigger(payload: DetectionWebhookPayload, db: Session = Depends(get_db)):
    return _handle_completion("ai_video", payload, db)


@router.post("/audio_trigger", dependencies=[Depends(_verify_secret)])
def audio_trigger(payload: DetectionWebhookPayload, db: Session = Depends(get_db)):
    return _handle_completion("ai_audio", payload, db)


@router.post("/lipsync_trigger", dependencies=[Depends(_verify_secret)])
def lipsync_trigger(payload: DetectionWebhookPayload, db: Session = Depends(get_db)):
    return _handle_completion("lipsync", payload, db)
