import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database import get_db
from models.notification import Notification
from models.user import User
from schemas.notifications import SendNotificationRequest
from utils.deps import get_current_user
from utils.errors import AppError
from utils.notification_templates import NOTIFICATION_TEMPLATES
from utils.push import send_push

router = APIRouter()


def _resolve_user_id(user_id: str) -> int:
    raw = user_id[len("usr_"):] if user_id.startswith("usr_") else user_id
    try:
        return int(raw)
    except ValueError:
        raise AppError("VALIDATION_ERROR", f"Invalid userId '{user_id}'.", 422)


def _notification_response(n: Notification) -> dict:
    return {
        "id": str(n.id),
        "template": n.template,
        "title": n.title,
        "body": n.body,
        "data": n.data or {},
        "read": n.read,
        "createdAt": n.created_at.isoformat() if n.created_at else None,
    }


# No auth dependency by design — this is an internal/service-triggered endpoint,
# meant to be called by your own backend code (or during dev, directly by userId)
# rather than by an end user acting on their own session.
@router.post("/send", status_code=201)
def send_notification(
    payload: SendNotificationRequest,
    db: Session = Depends(get_db),
):
    template = NOTIFICATION_TEMPLATES.get(payload.template)
    if not template:
        known = ", ".join(sorted(NOTIFICATION_TEMPLATES))
        raise AppError("VALIDATION_ERROR", f"Unknown template '{payload.template}'. Known templates: {known}.", 422)

    target = db.query(User).filter(User.id == _resolve_user_id(payload.userId)).first()
    if not target:
        raise AppError("NOT_FOUND", f"No user with id {payload.userId} was found.", 404)

    try:
        title = template["title"].format(**payload.data)
        body = template["body"].format(**payload.data)
    except KeyError as e:
        raise AppError("VALIDATION_ERROR", f"Template '{payload.template}' is missing field {e}.", 422)

    notification = Notification(
        user_id=target.id,
        template=payload.template,
        title=title,
        body=body,
        data=payload.data,
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)

    push_attempted = bool(target.push_token)
    if push_attempted:
        send_push(target.push_token, title, body, data={"template": payload.template, **payload.data})

    return {**_notification_response(notification), "pushAttempted": push_attempted}


@router.get("")
def list_notifications(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Notification).filter(Notification.user_id == current_user.id)
    total = q.count()
    unread = q.filter(Notification.read == False).count()  # noqa: E712
    items = q.order_by(Notification.created_at.desc()).offset((page - 1) * limit).limit(limit).all()

    return {
        "items": [_notification_response(n) for n in items],
        "total": total,
        "unread": unread,
        "page": page,
        "limit": limit,
        "hasMore": (page * limit) < total,
    }


@router.patch("/{notification_id}/read")
def mark_notification_read(
    notification_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        nid = uuid.UUID(notification_id)
    except ValueError:
        raise AppError("NOT_FOUND", f"No notification with id {notification_id} was found.", 404)

    notification = (
        db.query(Notification)
        .filter(Notification.id == nid, Notification.user_id == current_user.id)
        .first()
    )
    if not notification:
        raise AppError("NOT_FOUND", f"No notification with id {notification_id} was found.", 404)

    notification.read = True
    db.commit()
    db.refresh(notification)
    return _notification_response(notification)
