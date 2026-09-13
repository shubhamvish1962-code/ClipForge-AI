"""Clip-related models: CandidateClip, ClipScore, ClipVariant, Edit, Render, QAResult, ClipMetadata, Export."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import String, Text, Float, Integer, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CandidateClip(Base):
    __tablename__ = "candidate_clips"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    video_id: Mapped[str] = mapped_column(String(36), ForeignKey("videos.id"), nullable=False)
    start_time: Mapped[float] = mapped_column(Float, nullable=False)  # seconds
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    hook_time: Mapped[float | None] = mapped_column(Float, nullable=True)  # best hook start
    duration: Mapped[float] = mapped_column(Float, nullable=False)
    topic: Mapped[str] = mapped_column(String(500), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    reason: Mapped[str] = mapped_column(Text, default="")  # why selected — shown in UI
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="candidate")  # candidate | editing | qa | approved | rejected | needs_review
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False)
    transcript_text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # Relationships
    project = relationship("Project", back_populates="candidate_clips")
    scores = relationship("ClipScore", back_populates="candidate_clip", cascade="all, delete-orphan")
    variants = relationship("ClipVariant", back_populates="candidate_clip", cascade="all, delete-orphan")


class ClipScore(Base):
    """Virality score breakdown — one row per candidate, stores all 7 judge scores."""
    __tablename__ = "clip_scores"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_clip_id: Mapped[str] = mapped_column(String(36), ForeignKey("candidate_clips.id"), nullable=False, index=True)
    total_score: Mapped[float] = mapped_column(Float, default=0.0)  # 0–100

    # ── 7 Judge Scores ───────────────────────────────────────────────────
    hook_score: Mapped[float] = mapped_column(Float, default=0.0)         # /20
    curiosity_score: Mapped[float] = mapped_column(Float, default=0.0)    # /15
    story_score: Mapped[float] = mapped_column(Float, default=0.0)        # /15
    emotion_score: Mapped[float] = mapped_column(Float, default=0.0)      # /10
    pacing_score: Mapped[float] = mapped_column(Float, default=0.0)       # /10
    clarity_score: Mapped[float] = mapped_column(Float, default=0.0)      # /10
    visual_score: Mapped[float] = mapped_column(Float, default=0.0)       # /10
    shareability_score: Mapped[float] = mapped_column(Float, default=0.0) # /10

    # ── Agent Reasoning (JSON) ───────────────────────────────────────────
    judge_reasoning: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Example: {"hook": "Strong curiosity gap...", "story": "Complete arc..."}

    contested_dimensions: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    provider: Mapped[str] = mapped_column(String(50), default="mock")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # Relationships
    candidate_clip = relationship("CandidateClip", back_populates="scores")


class ClipVariant(Base):
    __tablename__ = "clip_variants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_clip_id: Mapped[str] = mapped_column(String(36), ForeignKey("candidate_clips.id"), nullable=False, index=True)
    variant_label: Mapped[str] = mapped_column(String(50), nullable=False)  # A, B, C, etc.
    variant_type: Mapped[str] = mapped_column(String(100), default="standard")
    description: Mapped[str] = mapped_column(Text, default="")
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    duration: Mapped[float] = mapped_column(Float, nullable=False)
    edit_instructions: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    caption_style: Mapped[str] = mapped_column(String(50), default="clean")
    crop_mode: Mapped[str] = mapped_column(String(50), default="auto")
    status: Mapped[str] = mapped_column(String(50), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # Relationships
    candidate_clip = relationship("CandidateClip", back_populates="variants")
    edits = relationship("Edit", back_populates="variant", cascade="all, delete-orphan")
    renders = relationship("Render", back_populates="variant", cascade="all, delete-orphan")
    qa_results = relationship("QAResult", back_populates="variant", cascade="all, delete-orphan")
    metadata_records = relationship("ClipMetadata", back_populates="variant", cascade="all, delete-orphan")
    exports = relationship("Export", back_populates="variant", cascade="all, delete-orphan")


class Edit(Base):
    __tablename__ = "edits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    variant_id: Mapped[str] = mapped_column(String(36), ForeignKey("clip_variants.id"), nullable=False, index=True)
    edit_type: Mapped[str] = mapped_column(String(50), nullable=False)  # trim, split, silence_remove, crop, caption, zoom, transition
    parameters: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # Relationships
    variant = relationship("ClipVariant", back_populates="edits")


class Render(Base):
    __tablename__ = "renders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    variant_id: Mapped[str] = mapped_column(String(36), ForeignKey("clip_variants.id"), nullable=False, index=True)
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    preview_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    thumbnail_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    width: Mapped[int] = mapped_column(Integer, default=1080)
    height: Mapped[int] = mapped_column(Integer, default=1920)
    aspect_ratio: Mapped[str] = mapped_column(String(20), default="9:16")
    duration: Mapped[float] = mapped_column(Float, default=0.0)
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    encoding: Mapped[str] = mapped_column(String(50), default="h264")
    status: Mapped[str] = mapped_column(String(50), default="pending")
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # Relationships
    variant = relationship("ClipVariant", back_populates="renders")


class QAResult(Base):
    __tablename__ = "qa_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    variant_id: Mapped[str] = mapped_column(String(36), ForeignKey("clip_variants.id"), nullable=False, index=True)
    qa_agent: Mapped[str] = mapped_column(String(100), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    issues: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # list of {issue, severity, description}
    recommendations: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # Relationships
    variant = relationship("ClipVariant", back_populates="qa_results")


class ClipMetadata(Base):
    __tablename__ = "clip_metadata"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    variant_id: Mapped[str] = mapped_column(String(36), ForeignKey("clip_variants.id"), nullable=False, index=True)
    titles: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # list of 3 title suggestions
    description: Mapped[str] = mapped_column(Text, default="")
    hashtags: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    keywords: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    thumbnail_frame_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    thumbnail_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # Relationships
    variant = relationship("ClipVariant", back_populates="metadata_records")


class Export(Base):
    __tablename__ = "exports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    variant_id: Mapped[str] = mapped_column(String(36), ForeignKey("clip_variants.id"), nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String(50), default="generic")
    preset: Mapped[str] = mapped_column(String(100), default="")
    aspect_ratio: Mapped[str] = mapped_column(String(20), default="9:16")
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # Relationships
    variant = relationship("ClipVariant", back_populates="exports")
