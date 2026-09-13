"""UserSettings, CaptionTemplate, and PlatformPreset models."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import String, Text, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserSettings(Base):
    __tablename__ = "user_settings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, unique=True)
    llm_provider: Mapped[str] = mapped_column(String(50), default="mock")
    llm_model: Mapped[str] = mapped_column(String(100), default="")
    speech_provider: Mapped[str] = mapped_column(String(50), default="mock")
    vision_provider: Mapped[str] = mapped_column(String(50), default="mock")
    default_clip_min_duration: Mapped[int] = mapped_column(Integer, default=30)
    default_clip_max_duration: Mapped[int] = mapped_column(Integer, default=90)
    default_caption_style: Mapped[str] = mapped_column(String(50), default="clean")
    default_aspect_ratio: Mapped[str] = mapped_column(String(20), default="9:16")
    language: Mapped[str] = mapped_column(String(10), default="en")
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    min_viral_score: Mapped[int] = mapped_column(Integer, default=50)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class CaptionTemplate(Base):
    __tablename__ = "caption_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    style_type: Mapped[str] = mapped_column(String(50), nullable=False)  # clean | bold | minimal | podcast | dynamic
    font_family: Mapped[str] = mapped_column(String(100), default="Inter")
    font_size: Mapped[int] = mapped_column(Integer, default=48)
    font_color: Mapped[str] = mapped_column(String(20), default="#FFFFFF")
    background_color: Mapped[str] = mapped_column(String(20), default="#00000080")
    highlight_color: Mapped[str] = mapped_column(String(20), default="#FBBF24")
    position_y: Mapped[int] = mapped_column(Integer, default=70)  # % from top
    max_line_width: Mapped[int] = mapped_column(Integer, default=30)  # chars
    animation: Mapped[str] = mapped_column(String(50), default="none")  # none | fade | pop | slide
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class PlatformPreset(Base):
    __tablename__ = "platform_presets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)  # youtube_shorts | instagram_reels | tiktok | generic
    width: Mapped[int] = mapped_column(Integer, default=1080)
    height: Mapped[int] = mapped_column(Integer, default=1920)
    aspect_ratio: Mapped[str] = mapped_column(String(20), default="9:16")
    max_duration: Mapped[int] = mapped_column(Integer, default=60)  # seconds
    encoding: Mapped[str] = mapped_column(String(50), default="h264")
    bitrate: Mapped[str] = mapped_column(String(20), default="8M")
    fps: Mapped[int] = mapped_column(Integer, default=30)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
