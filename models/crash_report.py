import uuid
from sqlalchemy import Column, String, Boolean, DateTime, Integer, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from database import Base


class CrashReport(Base):
    __tablename__ = "crash_reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    message = Column(Text, nullable=False)
    stack_trace = Column(Text, nullable=True)
    is_fatal = Column(Boolean, nullable=False, default=True)
    platform = Column(String, nullable=True)          # ios | android
    app_version = Column(String, nullable=True)
    os_version = Column(String, nullable=True)
    device_model = Column(String, nullable=True)
    context = Column(JSONB, nullable=True)             # arbitrary extra breadcrumbs
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="crash_reports")
