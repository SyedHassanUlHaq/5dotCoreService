"""
Detection request endpoints:
  POST   /scans   submit a file or a supported link (YouTube / Facebook / Instagram / X / TikTok), enqueue detection
"""

import os
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

import requests
import yt_dlp
from fastapi import APIRouter, BackgroundTasks, Depends, UploadFile, File, Form, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config.project_config import PLAN_SCAN_LIMITS, YOUTUBE_API_KEY
from database import SessionLocal, get_db
from models.detection_request import DetectionRequest
from models.user import User
from utils.deps import get_current_user
from utils.errors import AppError
from utils.s3 import upload_file, presigned_url, delete_file
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

# The app's scan UI only ever asks for one of these three at a time, but a
# DetectionRequest row supports any combination of the four underlying
# detection types — "video" bundles ai_video + lipsync into one combined
# result, since the frontend renders them as a single deepfake-video view.
SCAN_TYPE_DETECT_TYPES = {
    "video": {"ai_video", "lipsync"},
    "audio": {"ai_audio"},
    "tamper": {"changes"},
}
SCAN_TYPE_PRIORITY = ("video", "audio", "tamper")

_STAGE_STATUS = {
    None: "pending",
    "queued": "pending",
    "processing": "running",
    "complete": "complete",
    "failed": "complete",
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


def _detect_kwargs_for_scan_type(scan_type: str) -> dict:
    return {DETECT_FIELD_BY_TYPE[t]: True for t in SCAN_TYPE_DETECT_TYPES[scan_type]}


def _scan_type_of(dr: DetectionRequest) -> str | None:
    requested = set(_requested_types_of(dr))
    for scan_type in SCAN_TYPE_PRIORITY:
        if requested & SCAN_TYPE_DETECT_TYPES[scan_type]:
            return scan_type
    return None


def _result_for(dr: DetectionRequest, detect_type: str) -> dict:
    return (dr.result_data or {}).get(detect_type) or {}


def _scan_result_data(dr: DetectionRequest, scan_type: str) -> dict:
    """Best-effort read of whatever the downstream detection service reported.

    result_data has no fixed schema, it's whatever `payload.result` dict the
    matching webhook received, so every key here is read defensively and
    degrades to a neutral default if the service didn't include it.
    """
    if scan_type == "video":
        video = _result_for(dr, "ai_video")
        lipsync = _result_for(dr, "lipsync")
        return {
            "verdict": video.get("verdict") or lipsync.get("verdict"),
            "score": video.get("score") if video.get("score") is not None else lipsync.get("score"),
            "plainEnglishExplanation": video.get("plainEnglishExplanation") or lipsync.get("plainEnglishExplanation") or "",
            "segments": (video.get("segments") or []) + (lipsync.get("segments") or []),
        }
    detect_type = next(iter(SCAN_TYPE_DETECT_TYPES[scan_type]))
    return _result_for(dr, detect_type)


def _result_type_for(scan_type: str, verdict: str | None) -> str:
    if scan_type == "video":
        return "deepfakeVideo"
    if scan_type == "tamper":
        return "editTamper"
    return {"ai": "aiVoice", "tampered": "tampered"}.get(verdict, "authentic")


def _to_scan_list_item(dr: DetectionRequest) -> dict | None:
    scan_type = _scan_type_of(dr)
    if not scan_type:
        return None
    data = _scan_result_data(dr, scan_type)
    verdict = data.get("verdict")
    if not verdict:
        return None
    return {
        "scanId": str(dr.id),
        "filename": dr.filename,
        "duration": dr.duration or 0,
        "scanType": scan_type,
        "resultType": _result_type_for(scan_type, verdict),
        "verdict": verdict,
        "score": data.get("score") or 0,
        "completedAt": dr.completed_at.isoformat() if dr.completed_at else None,
    }


def _current_stage(dr: DetectionRequest) -> str | None:
    for t in _requested_types_of(dr):
        if getattr(dr, STATUS_FIELD_BY_TYPE[t]) not in ("complete", "failed"):
            return t
    return None


def _stages(dr: DetectionRequest) -> dict:
    return {
        t: {"status": _STAGE_STATUS.get(getattr(dr, STATUS_FIELD_BY_TYPE[t]), "pending")}
        for t in _requested_types_of(dr)
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
    scanType: str | None = Form(None),
    filename: str | None = Form(None),
    detectAiAudio: bool = Form(False),
    detectAiVideo: bool = Form(False),
    detectLipsync: bool = Form(False),
    detectChanges: bool = Form(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if bool(file) == bool(url):
        raise AppError("VALIDATION_ERROR", "Provide either a file or a url, not both.", 422)

    # The app submits a single `scanType` (audio/video/tamper) rather than the
    # four raw detect flags; when present it takes over from them entirely.
    if scanType:
        if scanType not in SCAN_TYPE_DETECT_TYPES:
            raise AppError("VALIDATION_ERROR", "scanType must be one of: audio, video, tamper.", 422)
        flags = _detect_kwargs_for_scan_type(scanType)
        detectAiAudio = flags.get("detect_ai_audio", False)
        detectAiVideo = flags.get("detect_ai_video", False)
        detectLipsync = flags.get("detect_lipsync", False)
        detectChanges = flags.get("detect_changes", False)

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
            filename=filename or url,
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
            "scanId": str(dr.id),
            "status": dr.status,
            "estimatedSeconds": 90,
            "uploadedAt": dr.created_at.isoformat() if dr.created_at else datetime.now(timezone.utc).isoformat(),
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
        filename=filename or file.filename or "upload",
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
        "scanId": str(dr.id),
        "status": dr.status,
        "estimatedSeconds": 90,
        "uploadedAt": dr.created_at.isoformat() if dr.created_at else datetime.now(timezone.utc).isoformat(),
    }


class SubmitUrlScanRequest(BaseModel):
    url: str
    scanType: str


@router.post("/url", status_code=202)
async def submit_url_scan(
    payload: SubmitUrlScanRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.scanType not in SCAN_TYPE_DETECT_TYPES:
        raise AppError("VALIDATION_ERROR", "scanType must be one of: audio, video, tamper.", 422)
    if not _is_supported_url(payload.url):
        raise AppError(
            "UNSUPPORTED_SOURCE",
            "Only YouTube, Facebook, Instagram, X, and TikTok links are supported.",
            422,
        )

    _check_quota(current_user)

    flags = _detect_kwargs_for_scan_type(payload.scanType)
    requested_types = _requested_types(
        flags.get("detect_ai_audio", False),
        flags.get("detect_ai_video", False),
        flags.get("detect_lipsync", False),
        flags.get("detect_changes", False),
    )

    dr = DetectionRequest(
        user_id=current_user.id,
        filename=payload.url,
        url_source=payload.url,
        detect_ai_audio=flags.get("detect_ai_audio", False),
        detect_ai_video=flags.get("detect_ai_video", False),
        detect_lipsync=flags.get("detect_lipsync", False),
        detect_changes=flags.get("detect_changes", False),
        status="processing",
    )
    db.add(dr)
    db.commit()
    db.refresh(dr)

    background_tasks.add_task(_process_url, str(dr.id), payload.url, requested_types)

    return {
        "scanId": str(dr.id),
        "status": dr.status,
        "estimatedSeconds": 90,
        "uploadedAt": dr.created_at.isoformat() if dr.created_at else datetime.now(timezone.utc).isoformat(),
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


@router.get("")
def list_scans(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    verdict: str | None = Query(None),
    scanType: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(DetectionRequest)
        .filter(DetectionRequest.user_id == current_user.id, DetectionRequest.status == "complete")
        .order_by(DetectionRequest.completed_at.desc())
        .all()
    )

    items = [item for dr in rows if (item := _to_scan_list_item(dr)) is not None]
    if verdict:
        items = [i for i in items if i["verdict"] == verdict]
    if scanType:
        items = [i for i in items if i["scanType"] == scanType]

    total = len(items)
    start = (page - 1) * limit
    page_items = items[start:start + limit]

    return {
        "items": page_items,
        "total": total,
        "page": page,
        "limit": limit,
        "hasMore": start + limit < total,
    }


@router.get("/{scan_id}")
def get_scan(
    scan_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    dr = (
        db.query(DetectionRequest)
        .filter(DetectionRequest.id == scan_id, DetectionRequest.user_id == current_user.id)
        .first()
    )
    if not dr:
        raise AppError("NOT_FOUND", "Scan not found.", 404)

    scan_type = _scan_type_of(dr)
    if not scan_type:
        raise AppError("NOT_FOUND", "Scan not found.", 404)

    data = _scan_result_data(dr, scan_type)
    verdict = data.get("verdict") or "authentic"
    score = data.get("score") or 0

    base = {
        "scanId": str(dr.id),
        "userId": f"usr_{dr.user_id}",
        "filename": dr.filename,
        "fileSize": dr.file_size or 0,
        "duration": dr.duration or 0,
        "scanType": scan_type,
        "verdict": verdict,
        "score": score,
        "status": dr.status,
        "createdAt": dr.created_at.isoformat() if dr.created_at else None,
        "completedAt": dr.completed_at.isoformat() if dr.completed_at else None,
    }

    if scan_type == "audio":
        base.update({
            "resultType": _result_type_for(scan_type, verdict),
            "bitrate": dr.bitrate or "",
            "tagline": data.get("tagline", ""),
            "waveformBars": data.get("waveformBars", []),
            "evidence": data.get("evidence", []),
        })
    elif scan_type == "video":
        base.update({
            "resultType": "deepfakeVideo",
            "thumbnailUrl": presigned_url(dr.thumbnail_key) if dr.thumbnail_key else "",
            "plainEnglishExplanation": data.get("plainEnglishExplanation", ""),
            "segments": data.get("segments", []),
        })
    else:  # tamper
        edits = data.get("edits", [])
        base.update({
            "resultType": "editTamper",
            "editCount": data.get("editCount", len(edits)),
            "editSummary": data.get("editSummary", ""),
            "tamperLevel": data.get("tamperLevel", "low"),
            "edits": edits,
        })

    return base


@router.get("/{scan_id}/status")
def get_scan_status(
    scan_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    dr = (
        db.query(DetectionRequest)
        .filter(DetectionRequest.id == scan_id, DetectionRequest.user_id == current_user.id)
        .first()
    )
    if not dr:
        raise AppError("NOT_FOUND", "Scan not found.", 404)

    return {
        "scanId": str(dr.id),
        "progress": _progress(dr),
        "currentStage": _current_stage(dr),
        "status": dr.status,
        "stages": _stages(dr),
        "estimatedSecondsRemaining": 0 if dr.status in ("complete", "failed") else 30,
    }


@router.delete("/{scan_id}", status_code=204)
def delete_scan(
    scan_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    dr = (
        db.query(DetectionRequest)
        .filter(DetectionRequest.id == scan_id, DetectionRequest.user_id == current_user.id)
        .first()
    )
    if not dr:
        raise AppError("NOT_FOUND", "Scan not found.", 404)

    if dr.file_key:
        delete_file(dr.file_key)
    db.delete(dr)
    db.commit()
    return None


# ---------------------------------------------------------------------------
# Trending — real trending deepfake/AI-generated videos pulled directly from
# YouTube, independent of whether anyone has scanned them here. If we happen
# to already have our own completed detection request for the same video,
# its result is attached if available; otherwise those fields are null and
# the app shows a neutral "Trending" badge instead of a fabricated AI score.
# ---------------------------------------------------------------------------

YOUTUBE_TRENDING_QUERY = 'deepfake OR "AI generated" OR "AI fake"'
TRENDING_CACHE_TTL_SECONDS = 60 * 60  # 1 hour — search.list is expensive on quota (100 units/call)
_trending_cache: dict = {"data": None, "expires_at": 0.0}


def _search_trending_youtube_videos(limit: int) -> list[dict]:
    """Query YouTube directly for recently popular deepfake/AI-generated videos."""
    if not YOUTUBE_API_KEY:
        return []
    try:
        published_after = (datetime.now(timezone.utc) - timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%SZ")
        search_resp = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "part": "snippet",
                "q": YOUTUBE_TRENDING_QUERY,
                "type": "video",
                "order": "viewCount",
                "publishedAfter": published_after,
                "maxResults": limit,
                "key": YOUTUBE_API_KEY,
            },
            timeout=5,
        )
        search_items = search_resp.json().get("items") or []
        video_ids = [it["id"]["videoId"] for it in search_items if it.get("id", {}).get("videoId")]
        if not video_ids:
            return []

        stats_resp = requests.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={"part": "statistics", "id": ",".join(video_ids), "key": YOUTUBE_API_KEY},
            timeout=5,
        )
        stats_by_id = {
            item["id"]: item.get("statistics", {})
            for item in (stats_resp.json().get("items") or [])
        }

        results = []
        for it in search_items:
            video_id = it.get("id", {}).get("videoId")
            if not video_id:
                continue
            snippet = it["snippet"]
            stats = stats_by_id.get(video_id, {})
            thumbnails = snippet.get("thumbnails", {})
            thumbnail = thumbnails.get("high") or thumbnails.get("medium") or thumbnails.get("default") or {}
            results.append({
                "videoId": video_id,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "title": snippet.get("title"),
                "channelTitle": snippet.get("channelTitle"),
                "thumbnailUrl": thumbnail.get("url"),
                "viewCount": int(stats["viewCount"]) if "viewCount" in stats else None,
                "likeCount": int(stats["likeCount"]) if "likeCount" in stats else None,
            })
        return results
    except Exception:
        return []


def _cached_trending_videos(limit: int) -> list[dict]:
    now = datetime.now(timezone.utc).timestamp()
    if _trending_cache["data"] is not None and _trending_cache["expires_at"] > now:
        return _trending_cache["data"][:limit]
    videos = _search_trending_youtube_videos(limit=10)
    _trending_cache["data"] = videos
    _trending_cache["expires_at"] = now + TRENDING_CACHE_TTL_SECONDS
    return videos[:limit]


def _own_detection_data(video_id: str, db: Session) -> dict:
    """Our own verdict/score for this video, if we've already processed it ourselves.

    DetectionRequest doesn't have first-class verdict/score columns — result
    fields live in `result_data` (JSONB), so this reads defensively and
    degrades to nulls if those keys aren't present yet.
    """
    rows = (
        db.query(DetectionRequest)
        .filter(DetectionRequest.url_source.ilike(f"%{video_id}%"), DetectionRequest.status == "complete")
        .order_by(DetectionRequest.created_at.desc())
        .all()
    )
    if not rows:
        return {"scanCount": None, "score": None, "verdict": None}
    latest_data = rows[0].result_data or {}
    return {
        "scanCount": len({r.user_id for r in rows}),
        "score": latest_data.get("score"),
        "verdict": latest_data.get("verdict"),
    }


@router.get("/trending")
def get_trending(
    limit: int = Query(5, ge=1, le=10),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    videos = _cached_trending_videos(limit)

    items = []
    for video in videos:
        own = _own_detection_data(video["videoId"], db)
        items.append({
            "url": video["url"],
            "scanCount": own["scanCount"],
            "score": own["score"],
            "verdict": own["verdict"],
            "youtube": {
                "title": video["title"],
                "channelTitle": video["channelTitle"],
                "thumbnailUrl": video["thumbnailUrl"],
                "viewCount": video["viewCount"],
                "likeCount": video["likeCount"],
            },
        })

    return {"items": items}
