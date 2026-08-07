from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from config.project_config import MODEL_VERSION
from database import get_db
from models.detection_request import DetectionRequest
from models.user import User
from utils.deps import get_current_user

router = APIRouter()

_MODEL_BENCHMARK_ACCURACY = 88.4
_CROSS_CHECKED_CASES = 240


@router.get("/weekly")
def weekly_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)

    # Start of current week (Monday)
    week_start = now - timedelta(days=now.weekday())
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)

    # Start of previous week
    prev_week_start = week_start - timedelta(days=7)

    user_scans = (
        db.query(DetectionRequest)
        .filter(DetectionRequest.user_id == current_user.id, DetectionRequest.status == "complete")
    )

    # Current week scans
    this_week = user_scans.filter(DetectionRequest.created_at >= week_start).all()

    # Previous week scans count for delta
    prev_week_count = (
        user_scans
        .filter(DetectionRequest.created_at >= prev_week_start, DetectionRequest.created_at < week_start)
        .count()
    )

    total_scans = user_scans.count()
    flagged = user_scans.filter(
        (DetectionRequest.overall_ai_video_score > 0.5) |
        (DetectionRequest.overall_ai_audio_score > 0.5)
    ).count()

    # Daily breakdown Mon–Sun of current week
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    day_counts = {d: 0 for d in day_names}
    for scan in this_week:
        created = scan.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        day_name = day_names[created.weekday()]
        day_counts[day_name] += 1

    daily_breakdown = [{"day": d, "scans": day_counts[d]} for d in day_names]

    this_week_count = len(this_week)
    accuracy_delta = round(current_user.accuracy_rate - _MODEL_BENCHMARK_ACCURACY, 1)

    return {
        "totalScans": total_scans,
        "flaggedScans": flagged,
        "accuracyRate": current_user.accuracy_rate,
        "accuracyDelta": accuracy_delta,
        "modelVersion": MODEL_VERSION,
        "modelBenchmarkAccuracy": _MODEL_BENCHMARK_ACCURACY,
        "crossCheckedCases": _CROSS_CHECKED_CASES,
        "dailyBreakdown": daily_breakdown,
    }
