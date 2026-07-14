"""
Detection request endpoints:
  POST   /scans   submit a file or a supported link (YouTube / Facebook / Instagram / X / TikTok), enqueue detection
"""

import os
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

import yt_dlp
from fastapi import APIRouter, BackgroundTasks, Depends, UploadFile, File, Form
from sqlalchemy.orm import Session

from config.project_config import PLAN_SCAN_LIMITS
from database import SessionLocal, get_db
from models.detection_request import DetectionRequest
from models.user import User
from utils.deps import get_current_user
from utils.errors import AppError
from utils.s3 import upload_file
from utils.sqs import enqueue_scan

router = APIRouter()

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".wav", ".m4a", ".mp3", ".opus"}
MAX_FILE_BYTES = 250 * 1024 * 512  # 125 MB
MAX_DURATION_SECONDS = 5 * 60      # 5 minutes

ALLOWED_URL_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be",
    "facebook.com", "www.facebook.com", "m.facebook.com", "fb.watch",
    "instagram.com", "www.instagram.com",
    "twitter.com", "www.twitter.com", "x.com", "www.x.com",
    "tiktok.com", "www.tiktok.com", "vm.tiktok.com",
}

STATUS_FIELD_BY_TYPE = {
    "ai_audio": "ai_audio_status",
    "ai_video": "ai_video_status",
    "lipsync": "lipsync_status",
    "changes": "changes_status",
}

DETECT_FIELD_BY_TYPE = {
    "ai_audio": "detect_ai_audio",
    "ai_video": "detect_ai_video",
    "lipsync": "detect_lipsync",
    "changes": "detect_changes",
}

PENDING_STATUSES = ("queued", "processing")

STATUS_PROGRESS = {
    None: 0,
    "queued": 0,
    "processing": 50,
    "complete": 100,
    "failed": 100,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_quota(user: User):
    limit = PLAN_SCAN_LIMITS.get(user.plan)
    if limit is not None and user.scans_used_this_month >= limit:
        raise AppError("SCAN_LIMIT_REACHED", "Monthly scan quota exhausted.", 429)


def _is_supported_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in ALLOWED_URL_HOSTS


def _probe_duration(path: str) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=30, check=True,
        )
        return float(out.stdout.strip())
    except Exception:
        raise AppError("VALIDATION_ERROR", "Could not read media duration.", 422)


def _requested_types(detect_ai_audio: bool, detect_ai_video: bool, detect_lipsync: bool, detect_changes: bool) -> list[str]:
    flags = {
        "ai_audio": detect_ai_audio,
        "ai_video": detect_ai_video,
        "lipsync": detect_lipsync,
        "changes": detect_changes,
    }
    return [t for t, requested in flags.items() if requested]


def _requested_types_of(dr: DetectionRequest) -> list[str]:
    return [t for t, field in DETECT_FIELD_BY_TYPE.items() if getattr(dr, field)]


def _progress(dr: DetectionRequest) -> int:
    types = _requested_types_of(dr)
    if not types:
        return 0
    total = sum(STATUS_PROGRESS.get(getattr(dr, STATUS_FIELD_BY_TYPE[t]), 0) for t in types)
    return round(total / len(types))


def _detections_summary(dr: DetectionRequest) -> dict:
    return {
        t: {"requested": getattr(dr, field), "status": getattr(dr, STATUS_FIELD_BY_TYPE[t])}
        for t, field in DETECT_FIELD_BY_TYPE.items()
        if getattr(dr, field)
    }


def _fail(db: Session, request_id: uuid.UUID, requested_types: list[str], message: str):
    dr = db.query(DetectionRequest).filter(DetectionRequest.id == request_id).first()
    if not dr:
        return
    dr.status = "failed"
    dr.error_message = message
    for t in requested_types:
        setattr(dr, STATUS_FIELD_BY_TYPE[t], "failed")
    dr.completed_at = datetime.now(timezone.utc)
    db.commit()


# ---------------------------------------------------------------------------
# Background work — runs after the response is returned
# ---------------------------------------------------------------------------

def _process_upload(request_id: str, tmp_path: str, ext: str, requested_types: list[str]):
    db = SessionLocal()
    rid = uuid.UUID(request_id)
    try:
        s3_key = f"clips/{request_id}{ext}"
        try:
            upload_file(tmp_path, s3_key, "application/octet-stream")
        except Exception as e:
            _fail(db, rid, requested_types, f"Upload failed: {e}")
            return
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        dr = db.query(DetectionRequest).filter(DetectionRequest.id == rid).first()
        if not dr:
            return
        dr.file_key = s3_key
        for t in requested_types:
            setattr(dr, STATUS_FIELD_BY_TYPE[t], "queued")
        db.commit()

        for t in requested_types:
            enqueue_scan(request_id, t, s3_key=s3_key)
    finally:
        db.close()


def _process_url(request_id: str, url: str, requested_types: list[str]):
    db = SessionLocal()
    rid = uuid.UUID(request_id)
    tmp_path = tempfile.mktemp(suffix=".mp4")
    try:
        try:
            with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True}) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as e:
            _fail(db, rid, requested_types, f"Could not read source video: {e}")
            return

        duration = info.get("duration")
        if duration and duration > MAX_DURATION_SECONDS:
            _fail(db, rid, requested_types, f"Video exceeds the {MAX_DURATION_SECONDS // 60} minute limit.")
            return

        try:
            ydl_opts = {"quiet": True, "outtmpl": tmp_path, "format": "mp4/bestvideo+bestaudio/best"}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except Exception as e:
            _fail(db, rid, requested_types, f"Download failed: {e}")
            return

        s3_key = f"clips/{request_id}.mp4"
        try:
            upload_file(tmp_path, s3_key, "video/mp4")
        except Exception as e:
            _fail(db, rid, requested_types, f"Upload failed: {e}")
            return

        dr = db.query(DetectionRequest).filter(DetectionRequest.id == rid).first()
        if not dr:
            return
        dr.file_key = s3_key
        dr.duration = duration
        if info.get("title"):
            dr.filename = info["title"]
        for t in requested_types:
            setattr(dr, STATUS_FIELD_BY_TYPE[t], "queued")
        db.commit()

        for t in requested_types:
            enqueue_scan(request_id, t, s3_key=s3_key)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        db.close()


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------

@router.post("", status_code=202)
async def create_detection_request(
    background_tasks: BackgroundTasks,
    file: UploadFile | None = File(None),
    url: str | None = Form(None),
    detectAiAudio: bool = Form(False),
    detectAiVideo: bool = Form(False),
    detectLipsync: bool = Form(False),
    detectChanges: bool = Form(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if bool(file) == bool(url):
        raise AppError("VALIDATION_ERROR", "Provide either a file or a url, not both.", 422)

    requested_types = _requested_types(detectAiAudio, detectAiVideo, detectLipsync, detectChanges)
    if not requested_types:
        raise AppError("VALIDATION_ERROR", "At least one detection type must be requested.", 422)

    _check_quota(current_user)

    if url:
        if not _is_supported_url(url):
            raise AppError(
                "UNSUPPORTED_SOURCE",
                "Only YouTube, Facebook, Instagram, X, and TikTok links are supported.",
                422,
            )

        dr = DetectionRequest(
            user_id=current_user.id,
            filename=url,
            url_source=url,
            detect_ai_audio=detectAiAudio,
            detect_ai_video=detectAiVideo,
            detect_lipsync=detectLipsync,
            detect_changes=detectChanges,
            status="processing",
        )
        db.add(dr)
        db.commit()
        db.refresh(dr)

        background_tasks.add_task(_process_url, str(dr.id), url, requested_types)

        return {
            "requestId": str(dr.id),
            "status": dr.status,
            "createdAt": dr.created_at.isoformat() if dr.created_at else datetime.now(timezone.utc).isoformat(),
        }

    # --- direct file ---
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise AppError("UNSUPPORTED_FORMAT", f"File type '{ext}' is not accepted.", 415)

    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        total_size = 0
        while chunk := await file.read(1024 * 1024):
            if total_size + len(chunk) > MAX_FILE_BYTES:
                tmp.close()
                os.remove(tmp.name)
                raise AppError("FILE_TOO_LARGE", f"File exceeds the {MAX_FILE_BYTES // (1024 * 1024)} MB limit.", 413)
            tmp.write(chunk)
            total_size += len(chunk)
        tmp_path = tmp.name

    duration = _probe_duration(tmp_path)
    if duration > MAX_DURATION_SECONDS:
        os.remove(tmp_path)
        raise AppError("VALIDATION_ERROR", f"File exceeds the {MAX_DURATION_SECONDS // 60} minute limit.", 422)

    dr = DetectionRequest(
        user_id=current_user.id,
        filename=file.filename or "upload",
        file_size=total_size,
        duration=duration,
        detect_ai_audio=detectAiAudio,
        detect_ai_video=detectAiVideo,
        detect_lipsync=detectLipsync,
        detect_changes=detectChanges,
        status="processing",
    )
    db.add(dr)
    db.commit()
    db.refresh(dr)

    background_tasks.add_task(_process_upload, str(dr.id), tmp_path, ext, requested_types)

    return {
        "requestId": str(dr.id),
        "status": dr.status,
        "createdAt": dr.created_at.isoformat() if dr.created_at else datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

@router.get("/pending")
def list_pending_requests(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(DetectionRequest)
        .filter(DetectionRequest.user_id == current_user.id, DetectionRequest.status.in_(PENDING_STATUSES))
        .order_by(DetectionRequest.created_at.desc())
        .all()
    )

    return {
        "items": [
            {
                "requestId": str(dr.id),
                "filename": dr.filename,
                "status": dr.status,
                "progress": _progress(dr),
                "detections": _detections_summary(dr),
                "createdAt": dr.created_at.isoformat() if dr.created_at else None,
            }
            for dr in rows
        ],
    }
