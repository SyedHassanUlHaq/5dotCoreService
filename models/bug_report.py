import uuid
from sqlalchemy import Column, String, DateTime, Integer, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from database import Base


class BugReport(Base):
    __tablename__ = "bug_reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    steps_to_reproduce = Column(Text, nullable=True)
    severity = Column(String, nullable=True)          # low | medium | high | critical
    status = Column(String, nullable=False, default="open")   # open | in_progress | resolved | wont_fix
    platform = Column(String, nullable=True)           # ios | android
    app_version = Column(String, nullable=True)
    os_version = Column(String, nullable=True)
    device_model = Column(String, nullable=True)
    context = Column(JSONB, nullable=True)              # arbitrary extra breadcrumbs
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="bug_reports")
