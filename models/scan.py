import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from database import Base


class Scan(Base):
    __tablename__ = "scans"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    filename = Column(String, nullable=False)
    file_key = Column(String, nullable=True)       # S3 object key
    url_source = Column(String, nullable=True)     # for URL-based scans
    file_size = Column(Integer, nullable=True)     # bytes
    duration = Column(Float, nullable=True)        # seconds
    bitrate = Column(String, nullable=True)        # e.g. "320 kbps"
    scan_type = Column(String, nullable=False)     # audio | video | tamper
    result_type = Column(String, nullable=True)    # aiVoice | authentic | tampered | deepfakeVideo | editTamper
    verdict = Column(String, nullable=True)        # ai | authentic | tampered
    score = Column(Integer, nullable=True)         # 0–100
    status = Column(String, nullable=False, default="queued")  # queued | processing | complete | failed
    progress = Column(Integer, nullable=False, default=0)
    current_stage = Column(String, nullable=True)
    thumbnail_key = Column(String, nullable=True)  # S3 key for video thumbnail
    result_data = Column(JSONB, nullable=True)     # type-specific result fields
    error_message = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="scans")
    feedback = relationship("Feedback", back_populates="scan")
