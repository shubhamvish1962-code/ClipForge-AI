"""
ClipForge AI — Application Configuration

Loads settings from environment variables / .env file.
Uses pydantic-settings for validation and type coercion.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings — loaded from environment / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────────────────
    app_name: str = "ClipForge AI"
    app_env: Literal["development", "production"] = "development"
    debug: bool = True
    secret_key: str = "change-me-to-a-long-random-secret"
    api_base_url: str = "http://localhost:8000"
    web_base_url: str = "http://localhost:3000"

    # ── Database ─────────────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./clipforge.db"

    # ── Redis ────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    use_redis: bool = False

    # ── Storage ──────────────────────────────────────────────────────────
    storage_backend: Literal["local", "s3"] = "local"
    local_storage_path: str = "./storage"
    max_upload_size_mb: int = 2000

    s3_bucket: str = ""
    s3_region: str = "us-east-1"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_endpoint_url: str = ""

    # ── AI Providers ─────────────────────────────────────────────────────
    llm_provider: Literal["mock", "openai", "anthropic", "gemini"] = "mock"
    speech_provider: Literal[
        "mock", "faster_whisper", "openai_whisper", "deepgram", "assemblyai"
    ] = "mock"

    # Local faster-whisper. "base" balances speed and accuracy on modest machines;
    # "auto" picks CUDA when available, else int8 on CPU.
    whisper_model_size: Literal["tiny", "base", "small", "medium", "large-v3"] = "base"
    whisper_device: str = "auto"
    whisper_compute_type: str = "auto"
    vision_provider: Literal["mock", "openai_vision", "google_vision"] = "mock"
    embedding_provider: Literal["mock", "openai_embeddings"] = "mock"

    openai_api_key: str = ""
    openai_llm_model: str = "gpt-4o"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_whisper_model: str = "whisper-1"

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"

    google_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    assemblyai_api_key: str = ""
    deepgram_api_key: str = ""
    google_application_credentials: str = ""

    # ── FFmpeg ───────────────────────────────────────────────────────────
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"

    # "auto" probes for a working NVENC encoder once per process and uses it
    # when available, falling back to libx264 per-clip on any encode failure.
    render_encoder: Literal["auto", "nvenc", "cpu"] = "auto"
    #: Renders running at once. Bounded because consumer NVENC drivers cap
    #: concurrent hardware encode sessions (commonly ~3-5).
    max_concurrent_renders: int = 3

    # ── Processing Limits ────────────────────────────────────────────────
    max_video_duration_seconds: int = 7200
    max_candidates: int = 50
    max_clip_variants: int = 5
    default_clip_min_duration: int = 30
    default_clip_max_duration: int = 90
    qa_max_retries: int = 3
    min_viral_score: int = 50

    # ── Auth / Security ──────────────────────────────────────────────────
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 30
    allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001,http://localhost:8000,http://127.0.0.1:8000"

    # ── Rate Limiting ────────────────────────────────────────────────────
    rate_limit_per_minute: int = 60

    # ── Demo & Mock Mode ─────────────────────────────────────────────────
    demo_mode: bool = True
    mock_mode: bool = True

    # ── Feature Flags ────────────────────────────────────────────────────
    enable_transcription: bool = True
    enable_smart_crop: bool = True
    enable_dynamic_captions: bool = True
    enable_broll: bool = False
    enable_motion_graphics: bool = False
    enable_ai_critic: bool = True
    enable_auto_revision: bool = True

    # ── Derived ──────────────────────────────────────────────────────────
    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def storage_path(self) -> Path:
        p = Path(self.local_storage_path)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def uploads_path(self) -> Path:
        p = self.storage_path / "uploads"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def processed_path(self) -> Path:
        p = self.storage_path / "processed"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def is_demo(self) -> bool:
        return self.demo_mode or self.llm_provider == "mock"


@lru_cache()
def get_settings() -> Settings:
    """Return cached settings singleton."""
    return Settings()
