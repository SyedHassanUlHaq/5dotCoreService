import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, String, Integer, Float, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from database import Base


class DetectionRequest(Base):
    __tablename__ = "detection_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    filename = Column(String, nullable=False)
    file_key = Column(String, nullable=True)       # S3 object key
    url_source = Column(String, nullable=True)     # for URL-based scans
    file_size = Column(Integer, nullable=True)     # bytes
    duration = Column(Float, nullable=True)        # seconds
    bitrate = Column(String, nullable=True)        # e.g. "320 kbps"
    detect_ai_audio = Column(Boolean, nullable=True)  # yes | no | unknown
    detect_ai_video = Column(Boolean, nullable=True)  # yes | no | unknown
    detect_lipsync = Column(Boolean, nullable=True)  # yes | no | unknown
    detect_changes = Column(Boolean, nullable=True)  # yes | no | unknown
    ai_audio_status = Column(String, nullable=True)  # queued | processing | complete | failed
    ai_video_status = Column(String, nullable=True)  # queued | processing | complete | failed
    lipsync_status = Column(String, nullable=True)  # queued | processing | complete | failed
    changes_status = Column(String, nullable=True)  # queued | processing | complete | failed
    status = Column(String, nullable=False, default="queued")  # queued | processing | complete | failed
    thumbnail_key = Column(String, nullable=True)  # S3 key for video thumbnail
    result_data = Column(JSONB, nullable=True)     # type-specific result fields
    error_message = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="scans")
    feedback = relationship("Feedback", back_populates="scan")
    chunks = relationship("Chunk", back_populates="detection_request", cascade="all, delete-orphan")


