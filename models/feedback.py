import uuid
from sqlalchemy import Column, String, Boolean, DateTime, Integer, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from database import Base


class Feedback(Base):
    __tablename__ = "feedback"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scan_id = Column(UUID(as_uuid=True), ForeignKey("detection_requests.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    correct_verdict = Column(String, nullable=False)   # authentic | ai | unsure
    reasons = Column(JSONB, nullable=True)             # string[]
    detail = Column(Text, nullable=True)
    allow_anonymized_copy = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    scan = relationship("DetectionRequest", back_populates="feedback")
    user = relationship("User", back_populates="feedback")
