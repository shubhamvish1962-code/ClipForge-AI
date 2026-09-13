"""
ClipForge AI — Smart Dynamic Crop & Framing Keyframe Generator.
Generates keyframe trajectories with smooth easing for vertical reframing,
punch-in zooms on high-retention moments, and speaker centering.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional, Tuple

from apps.api.schemas.editing_plan import CropKeyframe, ZoomEvent

logger = logging.getLogger("clipforge.video.crop_planner")


def _ease_in_out(t: float) -> float:
    """Cubic ease-in-out."""
    if t < 0.5:
        return 4 * t * t * t
    return 1 - math.pow(-2 * t + 2, 3) / 2


def _detect_emphasis_moments(
    transcript_words: List[Dict[str, Any]],
    clip_start: float = 0.0,
) -> List[Tuple[float, float, str]]:
    """
    Scans word timestamps to find punchline moments, contrast phrases, numbers, and questions.
    Returns (time_offset, intensity, reason) tuples.
    """
    moments = []
    if not transcript_words:
        return moments

    contrast_words = {"but", "however", "actually", "although", "though", "instead", "secret", "truth", "mistake"}
    strong_openers = {"listen", "look", "imagine", "why", "how", "never", "always"}

    for word_info in transcript_words:
        word_raw: str = word_info.get("word", "").strip()
        word_lower = word_raw.lower()
        start: float = word_info.get("start", 0.0)
        time_pos = max(0.0, start - clip_start)

        clean_w = "".join(c for c in word_lower if c.isalpha())

        # Question hook
        if "?" in word_raw:
            moments.append((time_pos, 1.08, "question"))
        # Numbers & Statistics
        elif any(c.isdigit() for c in word_raw):
            moments.append((time_pos, 1.07, "statistic"))
        # Contrast & revelation words
        elif clean_w in contrast_words:
            moments.append((time_pos, 1.09, "contrast"))
        # Strong commands/openers
        elif clean_w in strong_openers:
            moments.append((time_pos, 1.06, "hook"))

    return moments


def generate_smart_crop_plan(
    duration: float,
    transcript_words: Optional[List[Dict[str, Any]]] = None,
    crop_mode: str = "speaker_tracking",
) -> Tuple[List[CropKeyframe], List[ZoomEvent]]:
    """
    Generates a list of CropKeyframes and ZoomEvents for the EditingPlan.
    """
    if duration <= 0:
        return [CropKeyframe(time=0.0, zoom=1.0)], []

    words = transcript_words or []
    emphasis_moments = _detect_emphasis_moments(words)

    keyframes: List[CropKeyframe] = [CropKeyframe(time=0.0, zoom=1.0, ease="ease_in_out")]
    zoom_events: List[ZoomEvent] = []

    # If emphasis moments exist, schedule punch-ins
    if emphasis_moments:
        for t_pos, zoom_scale, reason in emphasis_moments[:4]:
            if t_pos + 1.0 < duration:
                # Punch in
                keyframes.append(CropKeyframe(time=t_pos, zoom=zoom_scale, ease="ease_in_out"))
                # Return to neutral after 2.5s
                return_time = min(duration, t_pos + 2.5)
                keyframes.append(CropKeyframe(time=return_time, zoom=1.0, ease="ease_in_out"))

                zoom_events.append(ZoomEvent(
                    start_time=t_pos,
                    duration=2.5,
                    zoom_scale=zoom_scale,
                    reason=reason,
                ))
    else:
        # Default breathing framing (prevents static shot fatigue)
        keyframes.extend([
            CropKeyframe(time=min(duration * 0.3, 4.0), zoom=1.06, ease="ease_in_out"),
            CropKeyframe(time=duration * 0.6, zoom=1.0, ease="ease_in_out"),
            CropKeyframe(time=min(duration * 0.85, duration - 1.5), zoom=1.07, ease="ease_in"),
        ])

    # Sort keyframes by time
    keyframes.sort(key=lambda k: k.time)
    return keyframes, zoom_events
