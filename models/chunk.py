import uuid
from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from database import Base


def normalize_lipsync_score(raw: float) -> float:
    """Shared by Chunk.lipsync_score_normalized below and the webhook
    handler's direct-result path (api/detection_webhooks.py, for the case
    where the worker sends a top-level score instead of only chunk data).

    Two confirmed quirks in this worker's convention, unlike ai_audio/
    ai_video:
      1. Scored 0-100, not 0-1.
      2. It's a match/sync-quality score (high = good sync), not a risk
         score (high = bad) like the other detection types — inverted here
         so every consumer can keep using the same `score >= threshold`
         "flag it" rule everywhere, without each caller re-deriving this.
    ai_audio and ai_video are already risk-scored natively and are left
    alone — this transform is lipsync-only.
    """
    scaled = raw / 100 if raw > 1 else raw
    return 1 - scaled


class Chunk(Base):
    __tablename__ = "detection_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    detection_request_id = Column(UUID(as_uuid=True), ForeignKey("detection_requests.id", ondelete="CASCADE"), nullable=False)
    chunk_index = Column(Integer, nullable=False)   # order of this chunk within the clip
    segment_start = Column(Float, nullable=False)   # clip segment start (seconds)
    segment_end = Column(Float, nullable=False)      # clip segment end (seconds)

    ai_audio_score = Column(Float, nullable=True)
    ai_audio_start = Column(Float, nullable=True)
    ai_audio_end = Column(Float, nullable=True)

    ai_video_score = Column(Float, nullable=True)
    ai_video_start = Column(Float, nullable=True)
    ai_video_end = Column(Float, nullable=True)

    lipsync_score = Column(Float, nullable=True)
    lipsync_start = Column(Float, nullable=True)
    lipsync_end = Column(Float, nullable=True)

    changes_points = Column(JSONB, nullable=True)   # list of timestamps (seconds) within this chunk

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    detection_request = relationship("DetectionRequest", back_populates="chunks")

    @property
    def lipsync_score_normalized(self) -> float | None:
        """Every consumer should read through this instead of the raw
        column — see normalize_lipsync_score() above for what it corrects."""
        if self.lipsync_score is None:
            return None
        return normalize_lipsync_score(self.lipsync_score)
