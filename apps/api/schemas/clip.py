"""Clip, Score, and Export schemas."""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, ConfigDict


class CandidateClipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    start_time: float
    end_time: float
    duration: float
    hook_time: Optional[float] = None
    topic: str = ""
    summary: str = ""
    reason: str = ""
    confidence: float = 0.85
    rank: Optional[int] = None
    is_selected: bool = False
    status: str = "approved"
    transcript_text: str = ""
    score: Optional["ViralScoreResponse"] = None


class ViralScoreResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total_score: float
    hook_score: float
    curiosity_score: float
    story_score: float
    emotion_score: float
    pacing_score: float
    clarity_score: float
    visual_score: float
    shareability_score: float
    judge_reasoning: Optional[dict] = None
    contested_dimensions: Optional[dict] = None
    confidence: float


class ClipVariantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    candidate_clip_id: str
    variant_label: str
    variant_type: str
    description: str
    start_time: float
    end_time: float
    duration: float
    caption_style: str
    crop_mode: str
    status: str
    render_url: Optional[str] = None
    qa_status: Optional[str] = None


class QAResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    qa_agent: str
    passed: bool
    score: float
    issues: Optional[list] = None
    recommendations: Optional[list] = None
    attempt: int


class ClipMetadataResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    titles: Optional[list[str]] = None
    description: str = ""
    hashtags: Optional[list[str]] = None
    keywords: Optional[list[str]] = None
    thumbnail_frame_time: Optional[float] = None


class ExportRequest(BaseModel):
    platform: str = "generic"
    aspect_ratio: str = "9:16"
    quality: str = "1080p"
    bitrate: str = "balanced"


class ExportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    variant_id: str
    platform: str
    aspect_ratio: str
    quality: str = "1080p"
    bitrate: str = "balanced"
    status: str
    file_path: Optional[str] = None
    file_size: int = 0
