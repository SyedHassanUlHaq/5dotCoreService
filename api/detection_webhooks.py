"""
Called by the downstream AI service repos to signal that a detection job
finished. Each route corresponds to one detection type; once every type the
user requested for that DetectionRequest has reached a terminal state, the
overall request is marked done and the user is notified.

  POST /video-trigger     -> ai_video
  POST /audio_trigger     -> ai_audio
  POST /lipsync_trigger   -> lipsync
"""

import os
import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from api.detection_request import STATUS_FIELD_BY_TYPE, _requested_types_of
from database import get_db
from models.detection_request import DetectionRequest
from models.notification import Notification
from schemas.detection_webhooks import DetectionWebhookPayload
from utils.errors import AppError
from utils.notification_templates import NOTIFICATION_TEMPLATES
from utils.push import send_push

router = APIRouter()

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")


def _verify_secret(x_webhook_secret: str | None = Header(None)):
    if not WEBHOOK_SECRET or not x_webhook_secret or not secrets.compare_digest(x_webhook_secret, WEBHOOK_SECRET):
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
        result_data = dr.result_data or {}
        result_data[detection_type] = payload.result
        dr.result_data = result_data

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
