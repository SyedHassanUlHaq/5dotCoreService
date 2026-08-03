"""
Insert a test DetectionRequest row directly into the DB.

Usage:
    python scripts/seed_detection_request.py --user-id 1
    python scripts/seed_detection_request.py --user-id 1 --ai-video --lipsync --filename clip.mp4
"""

import argparse
import math
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from models.chunk import Chunk
from models.detection_request import DetectionRequest
from models.user import User
from utils.s3 import upload_bytes, upload_file

TYPES = ("ai_audio", "ai_video", "lipsync", "changes")
CHUNK_SECONDS = 5.0


def _ensure_user(db, user_id: int) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        return user

    user = User(
        id=user_id,
        email=f"test-user-{user_id}@example.com",
        name=f"Test User {user_id}",
        plan="free",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    print(f"Created test user {user.id} ({user.email})")
    return user


def main():
    parser = argparse.ArgumentParser(description="Insert a test DetectionRequest row.")
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--filename", default="test-clip.mp4")
    parser.add_argument("--file-key", default=None, help="Defaults to clips/<random>.mp4")
    parser.add_argument("--url", default=None, help="Set this instead of --file-key to simulate a link submission")
    parser.add_argument("--source-file", default=None, help="Local file to actually upload to S3 for this request")
    parser.add_argument("--duration", type=float, default=42.0)
    for t in TYPES:
        parser.add_argument(f"--{t.replace('_', '-')}", action="store_true", help=f"Request the {t} detection type")
    args = parser.parse_args()

    requested = {t: getattr(args, t) for t in TYPES}
    if not any(requested.values()):
        requested = {"ai_audio": True, "ai_video": True, "lipsync": True, "changes": False}

    file_key = args.file_key
    if not args.url and not file_key:
        file_key = f"clips/{uuid.uuid4()}.mp4"

    if not args.url:
        if args.source_file:
            upload_file(args.source_file, file_key, content_type="video/mp4")
            print(f"Uploaded {args.source_file} to s3 key {file_key}")
        else:
            upload_bytes(b"placeholder test clip - not a real media file", file_key, content_type="application/octet-stream")
            print(f"Uploaded placeholder object to s3 key {file_key}")

    db = SessionLocal()
    try:
        _ensure_user(db, args.user_id)

        dr = DetectionRequest(
            user_id=args.user_id,
            filename=args.filename,
            file_key=file_key,
            url_source=args.url,
            duration=args.duration,
            detect_ai_audio=requested["ai_audio"],
            detect_ai_video=requested["ai_video"],
            detect_lipsync=requested["lipsync"],
            detect_changes=requested["changes"],
            ai_audio_status="queued" if requested["ai_audio"] else None,
            ai_video_status="queued" if requested["ai_video"] else None,
            lipsync_status="queued" if requested["lipsync"] else None,
            changes_status="queued" if requested["changes"] else None,
            status="processing",
        )
        db.add(dr)
        db.commit()
        db.refresh(dr)

        num_chunks = max(1, math.ceil((dr.duration or CHUNK_SECONDS) / CHUNK_SECONDS))
        for i in range(num_chunks):
            db.add(Chunk(
                detection_request_id=dr.id,
                chunk_index=i,
                segment_start=i * CHUNK_SECONDS,
                segment_end=min((i + 1) * CHUNK_SECONDS, dr.duration or CHUNK_SECONDS),
            ))
        db.commit()
    finally:
        db.close()

    active_types = [t for t, v in requested.items() if v]
    print(f"Created DetectionRequest {dr.id}")
    print(f"  file_key: {dr.file_key}")
    print(f"  url_source: {dr.url_source}")
    print(f"  requested types: {active_types}")
    print(f"  chunks created: {num_chunks} ({CHUNK_SECONDS}s each)")
    print()
    print("Enqueue a job for it with, e.g.:")
    for t in active_types:
        print(f"  python scripts/enqueue_test_job.py {dr.id} --type {t} "
              f"{'--s3-key ' + dr.file_key if dr.file_key else '--url ' + (dr.url_source or '')}")


if __name__ == "__main__":
    main()
