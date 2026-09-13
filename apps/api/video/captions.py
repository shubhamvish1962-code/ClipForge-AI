"""
ClipForge AI — Word-Level Animated ASS Subtitle Engine.
Generates Advanced SubStation Alpha (.ass) scripts with word-level highlight animation,
semantic keyword emphasis, and platform safe-zone margin controls.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from apps.api.schemas.editing_plan import CaptionConfig

logger = logging.getLogger("clipforge.video.captions")

STYLE_PRESETS: Dict[str, Dict[str, Any]] = {
    "clean": {
        "font_family": "Arial",
        "font_size": 48,
        "position": "bottom",
        "margin_bottom": 160,
        "primary_color": "&H00FFFFFF",
        "highlight_color": "&H00FFFFFF",
        "outline_color": "&H00000000",
        "outline_width": 1.5,
        "shadow_depth": 0.0,
        "word_highlight": False,
        "max_words_per_line": 6,
    },
    "creator": {
        "font_family": "Arial",
        "font_size": 64,
        "position": "center",
        "margin_bottom": 220,
        "primary_color": "&H00FFFFFF",
        "highlight_color": "&H0000FFFF",  # Bright Yellow in ASS BGR
        "outline_color": "&H00000000",
        "outline_width": 3.5,
        "shadow_depth": 1.5,
        "word_highlight": True,
        "max_words_per_line": 4,
    },
    "podcast": {
        "font_family": "Helvetica",
        "font_size": 50,
        "position": "bottom",
        "margin_bottom": 180,
        "primary_color": "&H00E8E8E8",
        "highlight_color": "&H0000D0FF",  # Soft Cyan in ASS BGR
        "outline_color": "&H00000000",
        "outline_width": 2.0,
        "shadow_depth": 1.0,
        "word_highlight": False,
        "max_words_per_line": 6,
    },
    "cinematic": {
        "font_family": "Times New Roman",
        "font_size": 44,
        "position": "bottom",
        "margin_bottom": 150,
        "primary_color": "&H00FFFFFF",
        "highlight_color": "&H00FFFFFF",
        "outline_color": "&H00000000",
        "outline_width": 1.2,
        "shadow_depth": 0.8,
        "word_highlight": False,
        "max_words_per_line": 6,
    },
    "high_retention": {
        "font_family": "Impact",
        "font_size": 72,
        "position": "center",
        "margin_bottom": 240,
        "primary_color": "&H00FFFFFF",
        "highlight_color": "&H0000A5FF",  # Vivid Gold/Orange in ASS BGR
        "outline_color": "&H00000000",
        "outline_width": 4.0,
        "shadow_depth": 2.5,
        "word_highlight": True,
        "max_words_per_line": 3,
    },
}


def _format_ass_time(seconds: float) -> str:
    """Convert float seconds into ASS standard timestamp format H:MM:SS.CC"""
    if seconds < 0:
        seconds = 0.0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    cents = int((seconds * 100) % 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cents:02d}"


def _group_words_into_lines(words: List[Dict[str, Any]], max_per_line: int) -> List[List[Dict[str, Any]]]:
    """Group word timestamp objects into readable line chunks."""
    lines = []
    for i in range(0, len(words), max(1, max_per_line)):
        lines.append(words[i : i + max_per_line])
    return lines


def generate_ass_file(
    words: List[Dict[str, Any]],
    config: CaptionConfig,
    output_path: Path | str,
    clip_duration: float,
    clip_start_offset: float = 0.0,
) -> Path:
    """
    Generate a broadcast-grade ASS file for word-level animated captions.
    Relative timestamps are mapped cleanly from 0.0 to clip_duration.
    """
    try:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        alignments = {"bottom": 2, "center": 5, "top": 8}
        alignment = alignments.get(config.position.lower(), 2)

        font_name = config.font_family or "Impact"
        font_size = config.font_size or 68

        ass_lines = [
            "[Script Info]",
            "ScriptType: v4.00+",
            "PlayResX: 1080",
            "PlayResY: 1920",
            "WrapStyle: 1",
            "ScaledBorderAndShadow: yes",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            f"Style: Default,{font_name},{font_size},{config.primary_color},&H000000FF,{config.outline_color},&H80000000,-1,0,0,0,100,100,0,0,1,{config.outline_width},{config.shadow_depth},{alignment},40,40,{config.margin_bottom},1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]

        if not words:
            # Write empty script
            with open(output_path, "w", encoding="utf-8") as f:
                f.write("\n".join(ass_lines))
            return output_path

        # Normalize word timestamps relative to clip start
        normalized_words = []
        for w in words:
            w_start = max(0.0, w.get("start", 0.0) - clip_start_offset)
            w_end = max(w_start + 0.15, w.get("end", w_start + 0.3) - clip_start_offset)
            if w_start <= clip_duration:
                normalized_words.append({
                    "word": w.get("word", "").strip(),
                    "start": w_start,
                    "end": min(clip_duration, w_end),
                })

        lines_of_words = _group_words_into_lines(normalized_words, config.max_words_per_line)
        emphasis_lower = [emp.lower() for emp in config.emphasis_keywords] if config.emphasis_keywords else []

        for line in lines_of_words:
            if not line:
                continue

            line_start = line[0]["start"]
            line_end = line[-1]["end"]

            if config.word_highlight:
                # Per-word highlight events
                for i, current_word in enumerate(line):
                    text_parts = []
                    for j, w in enumerate(line):
                        word_str = w["word"].upper()

                        # Check semantic emphasis
                        clean_w = "".join(c for c in word_str.lower() if c.isalnum())
                        is_emphasis = clean_w in emphasis_lower or any(c.isdigit() for c in clean_w)

                        if is_emphasis:
                            word_str = f"{{\\b1\\fscx115\\fscy115}}{word_str}{{\\b0\\fscx100\\fscy100}}"

                        if i == j:
                            # Active spoken word highlight
                            text_parts.append(f"{{\\1c{config.highlight_color}}}{word_str}{{\\1c{config.primary_color}}}")
                        else:
                            text_parts.append(word_str)

                    dialogue_text = " ".join(text_parts)
                    w_start_str = _format_ass_time(current_word["start"])
                    w_end_str = _format_ass_time(current_word["end"])

                    ass_lines.append(f"Dialogue: 0,{w_start_str},{w_end_str},Default,,0,0,0,,{dialogue_text}")
            else:
                # Standard line-by-line dialogue
                text_parts = []
                for w in line:
                    word_str = w["word"]
                    clean_w = "".join(c for c in word_str.lower() if c.isalnum())
                    is_emphasis = clean_w in emphasis_lower or any(c.isdigit() for c in clean_w)
                    if is_emphasis:
                        word_str = f"{{\\b1\\fscx115\\fscy115}}{word_str}{{\\b0\\fscx100\\fscy100}}"
                    text_parts.append(word_str)

                dialogue_text = " ".join(text_parts)
                l_start_str = _format_ass_time(line_start)
                l_end_str = _format_ass_time(line_end)
                ass_lines.append(f"Dialogue: 0,{l_start_str},{l_end_str},Default,,0,0,0,,{dialogue_text}")

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(ass_lines))

        logger.info(f"Generated ASS subtitle file with {len(normalized_words)} words at {output_path}")
        return output_path

    except Exception as e:
        logger.error(f"Failed to generate ASS file: {e}", exc_info=True)
        raise
