import uuid
from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from database import Base


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
