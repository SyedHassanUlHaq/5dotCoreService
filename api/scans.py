"""
Scan lifecycle endpoints:
  POST   /scans               upload file, enqueue task
  POST   /scans/url           submit a URL (YouTube / X)
  GET    /scans               list scans (history)
  GET    /scans/{id}          full result
  GET    /scans/{id}/status   progress polling
  DELETE /scans/{id}          delete scan
  POST   /scans/{id}/forensic-pdf
  GET    /scans/{id}/forensic-pdf/status
"""

import os
import tempfile
import uuid
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, UploadFile, File, Form, Query
from sqlalchemy.orm import Session

from config.project_config import PLAN_SCAN_LIMITS
from database import get_db
from models.scan import Scan
from models.user import User
from schemas.scans import UrlScanRequest
from utils.deps import get_current_user
from utils.errors import AppError
from utils.s3 import upload_file, delete_file, presigned_url
from utils.sqs import enqueue_scan

router = APIRouter()

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".wav", ".m4a", ".mp3", ".opus"}
MAX_FILE_BYTES = 250 * 1024 * 1024  # 250 MB


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_quota(user: User):
    limit = PLAN_SCAN_LIMITS.get(user.plan)
    if limit is not None and user.scans_used_this_month >= limit:
        raise AppError("SCAN_LIMIT_REACHED", "Monthly scan quota exhausted.", 429)


def _scan_id(scan: Scan) -> str:
    return str(scan.id)


def _scan_base(scan: Scan) -> dict:
    return {
        "scanId": _scan_id(scan),
        "userId": f"usr_{scan.user_id}",
        "filename": scan.filename,
        "fileSize": scan.file_size,
        "duration": scan.duration,
        "scanType": scan.scan_type,
        "resultType": scan.result_type,
        "verdict": scan.verdict,
        "score": scan.score,
        "status": scan.status,
        "createdAt": scan.created_at.isoformat() if scan.created_at else None,
        "completedAt": scan.completed_at.isoformat() if scan.completed_at else None,
    }


def _scan_full(scan: Scan) -> dict:
    result = _scan_base(scan)
    if scan.result_data:
        result.update(scan.result_data)
    # Attach thumbnail URL for video scans (presigned, 7 days)
    if scan.thumbnail_key and "thumbnailUrl" not in result:
        result["thumbnailUrl"] = presigned_url(scan.thumbnail_key, expires_in=86400 * 7)
    if scan.scan_type == "audio" and scan.bitrate:
        result["bitrate"] = scan.bitrate
    return result


def _list_item(scan: Scan) -> dict:
    return {
        "scanId": _scan_id(scan),
        "filename": scan.filename,
        "duration": scan.duration,
        "scanType": scan.scan_type,
        "resultType": scan.result_type,
        "verdict": scan.verdict,
        "score": scan.score,
        "completedAt": scan.completed_at.isoformat() if scan.completed_at else None,
    }


def _get_scan_or_404(scan_id: str, user: User, db: Session) -> Scan:
    try:
        sid = uuid.UUID(scan_id)
    except ValueError:
        raise AppError("SCAN_NOT_FOUND", f"No scan with id {scan_id} was found.", 404)
    scan = db.query(Scan).filter(Scan.id == sid, Scan.user_id == user.id).first()
    if not scan:
        raise AppError("SCAN_NOT_FOUND", f"No scan with id {scan_id} was found.", 404)
    return scan


# ---------------------------------------------------------------------------
# Upload & submit
# ---------------------------------------------------------------------------

@router.post("", status_code=202)
async def upload_scan(
    file: UploadFile = File(...),
    scanType: str = Form(...),
    filename: str | None = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if scanType not in ("audio", "video", "tamper"):
        raise AppError("VALIDATION_ERROR", "scanType must be 'audio', 'video', or 'tamper'.", 422)

    _check_quota(current_user)

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise AppError("UNSUPPORTED_FORMAT", f"File type '{ext}' is not accepted.", 415)

    display_name = filename or file.filename or "upload"

    # Save to temp file first, then stream to S3
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        total_size = 0
        while chunk := await file.read(1024 * 1024):
            if total_size + len(chunk) > MAX_FILE_BYTES:
                os.remove(tmp.name)
                raise AppError("FILE_TOO_LARGE", "File exceeds the 250 MB limit.", 413)
            tmp.write(chunk)
            total_size += len(chunk)
        tmp_path = tmp.name

    scan = Scan(
        user_id=current_user.id,
        filename=display_name,
        file_size=total_size,
        scan_type=scanType,
        status="queued",
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)

    # Upload to S3
    s3_key = f"scans/{scan.id}{ext}"
    try:
        upload_file(tmp_path, s3_key, file.content_type or "application/octet-stream")
        scan.file_key = s3_key
        db.commit()
    finally:
        os.remove(tmp_path)

    enqueue_scan(str(scan.id), scanType, s3_key=s3_key)

    return {
        "scanId": _scan_id(scan),
        "status": "queued",
        "estimatedSeconds": 8,
        "uploadedAt": scan.created_at.isoformat() if scan.created_at else datetime.now(timezone.utc).isoformat(),
    }


@router.post("/url", status_code=202)
def submit_url_scan(
    payload: UrlScanRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.scanType not in ("audio", "video", "tamper"):
        raise AppError("VALIDATION_ERROR", "scanType must be 'audio', 'video', or 'tamper'.", 422)

    _check_quota(current_user)

    scan = Scan(
        user_id=current_user.id,
        filename=payload.url,
        url_source=payload.url,
        scan_type=payload.scanType,
        status="queued",
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)

    enqueue_scan(str(scan.id), payload.scanType, url_source=payload.url)

    return {
        "scanId": _scan_id(scan),
        "status": "queued",
        "estimatedSeconds": 20,
        "uploadedAt": scan.created_at.isoformat() if scan.created_at else datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

@router.get("")
def list_scans(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
    verdict: str | None = Query(None),
    scanType: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Scan).filter(Scan.user_id == current_user.id)
    if verdict:
        q = q.filter(Scan.verdict == verdict)
    if scanType:
        q = q.filter(Scan.scan_type == scanType)

    total = q.count()
    scans = q.order_by(Scan.created_at.desc()).offset((page - 1) * limit).limit(limit).all()

    return {
        "items": [_list_item(s) for s in scans],
        "total": total,
        "page": page,
        "limit": limit,
        "hasMore": (page * limit) < total,
    }


# ---------------------------------------------------------------------------
# Single scan result
# ---------------------------------------------------------------------------

@router.get("/{scan_id}/status")
def get_scan_status(
    scan_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    scan = _get_scan_or_404(scan_id, current_user, db)
    return {
        "scanId": _scan_id(scan),
        "progress": scan.progress,
        "currentStage": scan.current_stage,
        "status": scan.status,
        "stages": {
            "decoding_stream": {"status": _stage_status(scan, "decoding_stream")},
            "spectral_analysis": {"status": _stage_status(scan, "spectral_analysis")},
            "frame_coherence": {"status": _stage_status(scan, "frame_coherence")},
            "cross_check_model": {"status": _stage_status(scan, "cross_check_model")},
        },
        "estimatedSecondsRemaining": max(0, int((100 - scan.progress) / 10)),
    }


def _stage_status(scan: Scan, stage: str) -> str:
    order = ["decoding_stream", "spectral_analysis", "frame_coherence", "cross_check_model"]
    if scan.status == "complete":
        return "complete"
    if scan.current_stage is None:
        return "pending"
    cur_idx = order.index(scan.current_stage) if scan.current_stage in order else -1
    stage_idx = order.index(stage)
    if stage_idx < cur_idx:
        return "complete"
    if stage_idx == cur_idx:
        return "running"
    return "pending"


@router.get("/{scan_id}")
def get_scan(
    scan_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    scan = _get_scan_or_404(scan_id, current_user, db)
    return _scan_full(scan)


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@router.delete("/{scan_id}", status_code=204)
def delete_scan(
    scan_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    scan = _get_scan_or_404(scan_id, current_user, db)
    if scan.file_key:
        delete_file(scan.file_key)
    if scan.thumbnail_key:
        delete_file(scan.thumbnail_key)
    db.delete(scan)
    db.commit()
    return None


# ---------------------------------------------------------------------------
# Forensic PDF
# ---------------------------------------------------------------------------

@router.post("/{scan_id}/forensic-pdf", status_code=202)
def generate_forensic_pdf(
    scan_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.plan not in ("pro", "team"):
        raise AppError("FORBIDDEN", "Forensic PDF reports require a Pro or Team plan.", 403)

    scan = _get_scan_or_404(scan_id, current_user, db)
    if scan.status != "complete":
        raise AppError("VALIDATION_ERROR", "Scan is not yet complete.", 422)

    from tasks.pdf_task import generate_pdf
    background_tasks.add_task(generate_pdf, str(scan.id))

    return {
        "status": "generating",
        "estimatedSeconds": 8,
    }


@router.get("/{scan_id}/forensic-pdf/status")
def forensic_pdf_status(
    scan_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    scan = _get_scan_or_404(scan_id, current_user, db)

    result_data = scan.result_data or {}
    pdf_url = result_data.get("forensicPdfUrl")

    if pdf_url:
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        return {"status": "complete", "downloadUrl": pdf_url, "expiresAt": expires_at}

    return {"status": "generating"}
