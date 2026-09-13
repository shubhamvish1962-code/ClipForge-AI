"""
ClipForge AI — Professional Editing Plan Data Models & Schemas.
Single Source of Truth for Video Post-Production and Rendering.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict


class CropKeyframe(BaseModel):
    """A single keyframe for dynamic crop/zoom and camera pan animation."""
    model_config = ConfigDict(from_attributes=True)

    time: float  # seconds into the clip
    zoom: float = 1.0  # 1.0 = no zoom, 1.15 = 15% zoom in
    x_offset: float = 0.0  # -1.0 to 1.0, pan left/right relative to center
    y_offset: float = 0.0  # -1.0 to 1.0, pan up/down relative to center
    ease: str = "ease_in_out"  # ease_in, ease_out, ease_in_out, linear


class ZoomEvent(BaseModel):
    """A timed punch-in zoom moment for visual emphasis."""
    model_config = ConfigDict(from_attributes=True)

    start_time: float
    duration: float = 2.5
    zoom_scale: float = 1.08  # 8% punch-in
    ease: str = "ease_in_out"
    reason: str = "emphasis"  # punchline, statistic, question, contrast


class CaptionConfig(BaseModel):
    """Configuration for word-level animated caption rendering."""
    model_config = ConfigDict(from_attributes=True)

    style: str = "high_retention"  # high_retention, creator, podcast, cinematic, clean
    font_family: str = "Impact"
    font_size: int = 68  # Base font size for 1080px wide canvas
    position: str = "center"  # bottom, center, top
    margin_bottom: int = 240  # Safe zone clearance from bottom
    emphasis_keywords: List[str] = Field(default_factory=list)
    word_highlight: bool = True
    primary_color: str = "&H00FFFFFF"  # ASS BGR format (White)
    highlight_color: str = "&H0000FFFF"  # ASS BGR format (Yellow/Gold)
    outline_color: str = "&H00000000"  # ASS BGR format (Black)
    outline_width: float = 3.5
    shadow_depth: float = 2.0
    max_words_per_line: int = 4  # Short-form readable chunking


class AudioConfig(BaseModel):
    """Broadcast-grade audio processing configuration."""
    model_config = ConfigDict(from_attributes=True)

    normalize: bool = True
    target_lufs: float = -14.0  # Social media broadcast standard
    noise_reduction: bool = True
    high_pass_hz: int = 80  # Remove sub-bass rumble
    compression: bool = True
    compression_ratio: float = 3.5  # Dynamic punch for speech
    speech_boost_db: float = 1.5


class ColorConfig(BaseModel):
    """Color correction & grading parameters."""
    model_config = ConfigDict(from_attributes=True)

    brightness: float = 0.01  # -1.0 to 1.0
    contrast: float = 1.06  # 0.5 to 2.0
    saturation: float = 1.08  # Subtle color pop for social feeds


class MotionGraphicEvent(BaseModel):
    """Visual text callout, statistics pill, or topic card."""
    model_config = ConfigDict(from_attributes=True)

    start_time: float
    end_time: float
    graphic_type: str = "statistic"  # statistic, quote_card, topic_badge, callout
    text: str
    subtext: Optional[str] = None
    position: str = "top_center"  # top_center, center, bottom_center


class BrollEvent(BaseModel):
    """Cutaway or supporting visual insertion."""
    model_config = ConfigDict(from_attributes=True)

    start_time: float
    end_time: float
    media_path: str
    transition: str = "fade"  # fade, slide, cut
    opacity: float = 1.0
    description: str = ""


class HookConfig(BaseModel):
    """Hook optimization & Cold Open configuration."""
    model_config = ConfigDict(from_attributes=True)

    enabled: bool = False
    hook_type: str = "direct"  # cold_open, direct, question, curiosity_gap, bold_claim
    hook_start: Optional[float] = None
    hook_duration: Optional[float] = None
    transition_sound: str = "whoosh"


class EditingPlan(BaseModel):
    """
    Complete Editing Plan — Single Source of Truth for Video Rendering.
    Every parameter is directly executed by FFmpeg in the post-production pipeline.
    """
    model_config = ConfigDict(from_attributes=True)

    # Identification
    clip_id: str = ""
    variant_label: str = "A"
    variant_name: str = "High-Retention Master"
    style_category: str = "technology"  # podcast, educational, storytelling, technology

    # Clip Boundaries
    source_start_time: float = 0.0
    source_end_time: float = 30.0
    target_duration: float = 30.0

    # Framing & Canvas
    aspect_ratio: str = "9:16"  # 9:16, 1:1, 16:9
    target_width: int = 1080
    target_height: int = 1920
    crop_mode: str = "speaker_tracking"  # speaker_tracking, dynamic_zoom, center_fit

    # Timeline Modifiers
    hook: HookConfig = Field(default_factory=HookConfig)
    crop_keyframes: List[CropKeyframe] = Field(default_factory=list)
    zoom_events: List[ZoomEvent] = Field(default_factory=list)
    captions: CaptionConfig = Field(default_factory=CaptionConfig)
    burn_captions: bool = True
    audio: AudioConfig = Field(default_factory=AudioConfig)
    color: ColorConfig = Field(default_factory=ColorConfig)
    graphics: List[MotionGraphicEvent] = Field(default_factory=list)
    broll: List[BrollEvent] = Field(default_factory=list)

    # Encoding & Quality
    quality: str = "high"  # draft, high, maximum
    crf: int = 20  # Constant Rate Factor (18=crisp, 20=high quality)
    preset: str = "medium"
    video_bitrate: str = "8M"
    audio_bitrate: str = "192k"


class EditReport(BaseModel):
    """Structured report of all AI post-production edits made to the clip."""
    model_config = ConfigDict(from_attributes=True)

    clip_id: str
    variant_label: str = "A"
    hook_type: str
    hook_score: int
    pacing_rating: str  # Fast, Balanced, Narrative
    framing_changes_count: int
    zooms_applied_count: int
    captions_style: str
    keywords_emphasized: List[str]
    audio_mastering_applied: bool
    qc_passed: bool
    qc_critic_score: int
    short_form_potential_score: int
    technical_quality_score: int


def create_variant_editing_plans(
    clip_id: str,
    start_time: float,
    end_time: float,
    transcript_words: Optional[List[Dict[str, Any]]] = None,
    topic: str = "Technology & Product",
) -> List[EditingPlan]:
    """
    Generate 5 distinct professional Editing Plans for high-quality multi-variant output.
    """
    duration = max(1.0, end_time - start_time)
    words = transcript_words or []

    # Extract semantic keywords for emphasis (numbers, power verbs, core subjects)
    emphasis = []
    for w in words:
        raw = w.get("word", "").strip()
        clean = "".join(c for c in raw if c.isalnum())
        if any(c.isdigit() for c in clean) or (len(clean) >= 6 and raw[:1].isupper()):
            if clean not in emphasis:
                emphasis.append(clean)

    # Dynamic zoom keyframes
    keyframed_zooms = [
        CropKeyframe(time=0.0, zoom=1.0),
        CropKeyframe(time=min(duration * 0.25, 4.0), zoom=1.07, ease="ease_in_out"),
        CropKeyframe(time=duration * 0.55, zoom=1.0, ease="ease_in_out"),
        CropKeyframe(time=min(duration * 0.8, duration - 2.0), zoom=1.08, ease="ease_in"),
    ]

    # Variant A: High-Retention Master (Bold animated Gold captions + punch-in zooms)
    plan_a = EditingPlan(
        clip_id=clip_id,
        variant_label="A",
        variant_name="🔥 High-Retention Master",
        source_start_time=start_time,
        source_end_time=end_time,
        target_duration=duration,
        crop_keyframes=keyframed_zooms,
        captions=CaptionConfig(
            style="high_retention",
            font_family="Impact",
            font_size=72,
            position="center",
            margin_bottom=220,
            primary_color="&H00FFFFFF",
            highlight_color="&H0000A5FF",  # Gold/Orange in ASS
            outline_width=4.0,
            shadow_depth=2.0,
            max_words_per_line=3,
            emphasis_keywords=emphasis[:8],
            word_highlight=True,
        ),
        audio=AudioConfig(normalize=True, target_lufs=-14.0, compression=True, noise_reduction=True),
        color=ColorConfig(brightness=0.01, contrast=1.07, saturation=1.10),
        quality="high",
        crf=20,
    )

    # Variant B: Clean Creator (Yellow highlight captions, subtle framing)
    plan_b = EditingPlan(
        clip_id=clip_id,
        variant_label="B",
        variant_name="✨ Clean Creator",
        source_start_time=start_time,
        source_end_time=end_time,
        target_duration=duration,
        crop_keyframes=[
            CropKeyframe(time=0.0, zoom=1.0),
            CropKeyframe(time=duration * 0.4, zoom=1.05, ease="ease_in_out"),
            CropKeyframe(time=duration * 0.75, zoom=1.0, ease="ease_in_out"),
        ],
        captions=CaptionConfig(
            style="creator",
            font_family="Arial",
            font_size=64,
            position="center",
            margin_bottom=200,
            primary_color="&H00FFFFFF",
            highlight_color="&H0000FFFF",  # Yellow in ASS
            outline_width=3.0,
            shadow_depth=1.5,
            max_words_per_line=4,
            emphasis_keywords=emphasis[:6],
            word_highlight=True,
        ),
        audio=AudioConfig(normalize=True, target_lufs=-14.0, compression=True),
        color=ColorConfig(brightness=0.0, contrast=1.04, saturation=1.05),
        quality="high",
        crf=20,
    )

    # Variant C: Podcast & Interview (Speaker-focused, minimal captions)
    plan_c = EditingPlan(
        clip_id=clip_id,
        variant_label="C",
        variant_name="🎙️ Podcast Studio",
        source_start_time=start_time,
        source_end_time=end_time,
        target_duration=duration,
        crop_keyframes=[CropKeyframe(time=0.0, zoom=1.0)],
        captions=CaptionConfig(
            style="podcast",
            font_family="Helvetica",
            font_size=52,
            position="bottom",
            margin_bottom=180,
            primary_color="&H00F0F0F0",
            highlight_color="&H0000D0FF",
            outline_width=2.0,
            shadow_depth=1.0,
            max_words_per_line=6,
            word_highlight=False,
        ),
        audio=AudioConfig(normalize=True, target_lufs=-14.0, high_pass_hz=100, compression=True),
        color=ColorConfig(brightness=0.0, contrast=1.02, saturation=1.0),
        quality="high",
        crf=21,
    )

    # Variant D: Cinematic Storytelling (Elegant serif typography, rich contrast)
    plan_d = EditingPlan(
        clip_id=clip_id,
        variant_label="D",
        variant_name="🎬 Cinematic Narrative",
        source_start_time=start_time,
        source_end_time=end_time,
        target_duration=duration,
        crop_keyframes=[
            CropKeyframe(time=0.0, zoom=1.02),
            CropKeyframe(time=duration * 0.5, zoom=1.06, ease="ease_in_out"),
            CropKeyframe(time=duration * 0.95, zoom=1.02, ease="ease_out"),
        ],
        captions=CaptionConfig(
            style="cinematic",
            font_family="Times New Roman",
            font_size=46,
            position="bottom",
            margin_bottom=160,
            primary_color="&H00FFFFFF",
            highlight_color="&H00FFFFFF",
            outline_width=1.5,
            shadow_depth=1.0,
            max_words_per_line=6,
            word_highlight=False,
        ),
        audio=AudioConfig(normalize=True, target_lufs=-15.0, compression=True),
        color=ColorConfig(brightness=0.01, contrast=1.08, saturation=0.98),
        quality="maximum",
        crf=18,
    )

    # Variant E: Cyberpunk / Tech Insights (Neon cyan highlight, fast pacing)
    plan_e = EditingPlan(
        clip_id=clip_id,
        variant_label="E",
        variant_name="⚡ Cyberpunk Tech",
        source_start_time=start_time,
        source_end_time=end_time,
        target_duration=duration,
        crop_keyframes=keyframed_zooms,
        captions=CaptionConfig(
            style="creator",
            font_family="Impact",
            font_size=68,
            position="center",
            margin_bottom=220,
            primary_color="&H00FFFFFF",
            highlight_color="&H00FFFF00",  # Cyan in ASS (BGR)
            outline_width=3.5,
            shadow_depth=2.0,
            max_words_per_line=3,
            emphasis_keywords=emphasis[:8],
            word_highlight=True,
        ),
        audio=AudioConfig(normalize=True, target_lufs=-14.0, compression=True),
        color=ColorConfig(brightness=0.02, contrast=1.08, saturation=1.12),
        quality="high",
        crf=20,
    )

    return [plan_a, plan_b, plan_c, plan_d, plan_e]
