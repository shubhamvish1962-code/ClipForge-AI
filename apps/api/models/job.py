"""ProcessingJob and AgentRun models."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import String, Text, Float, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    job_type: Mapped[str] = mapped_column(String(100), nullable=False)  # full_pipeline | render | export | qa
    status: Mapped[str] = mapped_column(
        String(50), default="queued"
    )  # queued | processing | completed | failed | cancelled
    current_stage: Mapped[str] = mapped_column(String(100), default="")
    progress: Mapped[float] = mapped_column(Float, default=0.0)  # 0–100
    stages_completed: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    stages_total: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # Relationships
    project = relationship("Project", back_populates="processing_jobs")


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    job_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("processing_jobs.id"), nullable=True)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    input_reference: Mapped[str] = mapped_column(Text, default="")  # e.g. video_id, clip_id
    output_reference: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(50), default="running")  # running | success | failed | skipped
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    reasoning: Mapped[str] = mapped_column(Text, default="")
    provider: Mapped[str] = mapped_column(String(50), default="")
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    project = relationship("Project", back_populates="agent_runs")
