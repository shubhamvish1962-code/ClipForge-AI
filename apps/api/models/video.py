"""Video and VideoMetadata models."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import String, Text, Float, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(36), ForeignKey("sources.id"), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    proxy_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="ingested")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # Relationships
    project = relationship("Project", back_populates="videos")
    metadata_record = relationship("VideoMetadata", back_populates="video", uselist=False, cascade="all, delete-orphan")


class VideoMetadata(Base):
    __tablename__ = "video_metadata"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    video_id: Mapped[str] = mapped_column(String(36), ForeignKey("videos.id"), nullable=False, unique=True)
    duration: Mapped[float] = mapped_column(Float, default=0.0)  # seconds
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    fps: Mapped[float] = mapped_column(Float, default=0.0)
    codec: Mapped[str] = mapped_column(String(50), default="")
    audio_codec: Mapped[str] = mapped_column(String(50), default="")
    audio_tracks: Mapped[int] = mapped_column(Integer, default=1)
    file_size: Mapped[int] = mapped_column(Integer, default=0)  # bytes
    bitrate: Mapped[int] = mapped_column(Integer, default=0)
    aspect_ratio: Mapped[str] = mapped_column(String(20), default="16:9")
    thumbnails: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # list of thumbnail paths
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # Relationships
    video = relationship("Video", back_populates="metadata_record")
