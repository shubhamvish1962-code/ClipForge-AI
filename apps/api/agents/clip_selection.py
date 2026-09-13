"""
Clip selection — cheap prefilter, then one batched LLM call.

Strategy: run free signals over the whole transcript to reduce an hour of
content to a few dozen plausible windows, then spend exactly one LLM call
ranking those. Asking a model about the full transcript repeatedly is the
expensive way to get a worse answer.

Windows are always cut on transcript-segment boundaries, so a clip never opens
or closes mid-sentence.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("clipforge.agents.selection")

# Short-form targets. Windows outside this range are not considered.
MIN_CLIP_SECONDS = 12.0
MAX_CLIP_SECONDS = 75.0
IDEAL_CLIP_SECONDS = 35.0

#: Per-candidate excerpt cap sent to the model.
MAX_CANDIDATE_CHARS = 900

#: How many prefiltered windows get sent to the model.
MAX_CANDIDATES_FOR_LLM = 30

_FILLER_OPENERS = ("and ", "but ", "so ", "because ", "which ", "that ", "or ")


@dataclass
class Window:
    """A contender clip, aligned to transcript segment boundaries."""

    start: float
    end: float
    text: str
    segment_indices: list[int] = field(default_factory=list)
    signals: dict[str, Any] = field(default_factory=dict)
    cheap_score: float = 0.0

    @property
    def duration(self) -> float:
        return self.end - self.start


# ── Step 1: cheap prefilter ──────────────────────────────────────────────


def build_candidate_windows(segments: list[dict]) -> list[Window]:
    """
    Assemble every reasonable run of consecutive segments into a window.

    Segment boundaries are where the speaker actually paused, so building from
    them gives clean edges for free.
    """
    windows: list[Window] = []
    n = len(segments)

    for i in range(n):
        for j in range(i, n):
            start = float(segments[i].get("start", 0.0))
            end = float(segments[j].get("end", 0.0))
            duration = end - start

            if duration < MIN_CLIP_SECONDS:
                continue
            if duration > MAX_CLIP_SECONDS:
                break  # extending j only makes it longer

            text = " ".join(str(s.get("text", "")).strip() for s in segments[i:j + 1]).strip()
            if not text:
                continue

            windows.append(Window(
                start=start,
                end=end,
                text=text,
                segment_indices=list(range(i, j + 1)),
            ))

    for w in windows:
        w.signals = _compute_signals(w, segments)
        w.cheap_score = _score_window(w)

    return windows


def _compute_signals(window: Window, segments: list[dict]) -> dict[str, Any]:
    """Free signals — no model, no audio decode."""
    text = window.text
    first_idx = window.segment_indices[0]
    last_idx = window.segment_indices[-1]

    words = text.split()
    word_count = len(words)
    duration = max(window.duration, 0.001)

    # A question that opens the window and gets answered inside it is a
    # strong "self-contained moment" signal.
    first_text = str(segments[first_idx].get("text", "")).strip()
    opens_with_question = first_text.endswith("?")
    answered = opens_with_question and last_idx > first_idx

    # Pause before the window start = a natural entry point.
    pause_before = 0.0
    if first_idx > 0:
        pause_before = float(segments[first_idx].get("start", 0.0)) - float(
            segments[first_idx - 1].get("end", 0.0)
        )

    # Numbers and contrast words tend to mark quotable claims.
    has_numbers = bool(re.search(r"\b\d[\d,.]*\s*(%|percent|x|million|billion|k)?\b", text, re.I))
    contrast = len(re.findall(
        r"\b(but|however|actually|instead|until|turns out|the truth|nobody|everyone)\b",
        text, re.I,
    ))

    starts_mid_thought = first_text.lower().startswith(_FILLER_OPENERS)

    speakers = {segments[k].get("speaker") for k in window.segment_indices}

    return {
        "word_count": word_count,
        "words_per_second": round(word_count / duration, 2),
        "opens_with_question": opens_with_question,
        "question_answered": answered,
        "pause_before": round(max(0.0, pause_before), 2),
        "has_numbers": has_numbers,
        "contrast_markers": contrast,
        "starts_mid_thought": starts_mid_thought,
        "speaker_count": len([s for s in speakers if s]),
    }


def _score_window(window: Window) -> float:
    """
    Rank windows cheaply so only the promising ones reach the model.

    Deliberately crude — its only job is to avoid paying for obviously weak
    candidates. Final ordering is the model's call.
    """
    s = window.signals
    score = 0.0

    # Prefer durations near the short-form sweet spot.
    score += max(0.0, 10.0 - abs(window.duration - IDEAL_CLIP_SECONDS) / 4.0)

    if s["question_answered"]:
        score += 8.0
    if s["has_numbers"]:
        score += 4.0
    score += min(6.0, s["contrast_markers"] * 2.0)
    if s["pause_before"] > 0.4:
        score += 3.0
    if s["starts_mid_thought"]:
        score -= 6.0

    # Too sparse is dead air; too dense is unintelligible.
    wps = s["words_per_second"]
    if 1.8 <= wps <= 3.6:
        score += 4.0
    elif wps < 1.0:
        score -= 4.0

    if s["word_count"] < 25:
        score -= 5.0

    return round(score, 2)


def prefilter(windows: list[Window], limit: int = MAX_CANDIDATES_FOR_LLM) -> list[Window]:
    """Best-scoring windows, de-overlapped so the model sees distinct moments."""
    ordered = sorted(windows, key=lambda w: w.cheap_score, reverse=True)
    chosen: list[Window] = []

    for w in ordered:
        if len(chosen) >= limit:
            break
        # Skip anything that mostly repeats a window already chosen.
        if any(_overlap_ratio(w, c) > 0.6 for c in chosen):
            continue
        chosen.append(w)

    return sorted(chosen, key=lambda w: w.start)


def _overlap_ratio(a: Window, b: Window) -> float:
    overlap = min(a.end, b.end) - max(a.start, b.start)
    if overlap <= 0:
        return 0.0
    return overlap / min(a.duration, b.duration)


# ── Step 2: one batched LLM call ─────────────────────────────────────────

SELECTION_SYSTEM = (
    "You are a short-form video editor. You pick moments from a long video that "
    "work as standalone vertical clips for TikTok, Reels and Shorts. You judge "
    "only what is in the transcript and you never invent timestamps."
)

SELECTION_SCHEMA = {
    "clips": [
        {
            "candidate_id": "int — the id shown next to the candidate",
            "hook_strength": "int 0-100 — will the first 3 seconds stop a scroll",
            "story_completeness": "int 0-100 — does it stand alone without context",
            "emotional_impact": "int 0-100",
            "shareability": "int 0-100",
            "overall": "int 0-100 — your ranking score",
            "title": "string — punchy clip title, max 60 chars",
            "reason": "string — one sentence on why this works",
        }
    ]
}


async def select_with_llm(
    candidates: list[Window],
    provider: Any,
    topic: str = "",
    max_clips: int = 7,
) -> Optional[list[dict]]:
    """
    Ask the model to rank the prefiltered candidates. One call, all candidates.

    Returns None when the model is unavailable or unparseable so the caller can
    fall back rather than crash the pipeline.
    """
    if not candidates:
        return None

    lines = []
    for idx, w in enumerate(candidates):
        lines.append(
            f"[{idx}] {w.start:.1f}s-{w.end:.1f}s ({w.duration:.0f}s)\n{w.text.strip()}"
        )
    block = "\n\n".join(lines)

    instruction = (
        f"Below are {len(candidates)} candidate moments from a video"
        + (f" about: {topic}" if topic else "")
        + ".\n\n"
        f"Pick the {max_clips} best as standalone short-form clips and score each.\n"
        "Rules:\n"
        "- Use only the candidate_id values shown in brackets.\n"
        "- Prefer moments with a clear hook and a payoff inside the clip.\n"
        "- Reject anything that needs surrounding context to make sense.\n"
        "- Return them ordered best first."
    )

    try:
        result = await provider.analyze(
            content=block,
            instruction=instruction,
            schema=SELECTION_SCHEMA,
        )
    except Exception as e:
        logger.warning(f"LLM selection failed: {e}")
        return None

    parsed = result.get("parsed")
    if parsed is None:
        try:
            parsed = json.loads(result.get("text", ""))
        except (json.JSONDecodeError, TypeError):
            logger.warning("LLM selection returned unparseable output")
            return None

    picks = parsed.get("clips") if isinstance(parsed, dict) else parsed
    if not isinstance(picks, list) or not picks:
        logger.warning("LLM selection returned no clips")
        return None

    return _materialise(picks, candidates, max_clips)


def _materialise(picks: list[dict], candidates: list[Window], max_clips: int) -> list[dict]:
    """Turn model picks back into concrete clips, dropping anything invalid."""
    out: list[dict] = []
    seen: set[int] = set()

    for pick in picks:
        if not isinstance(pick, dict):
            continue
        try:
            cid = int(pick.get("candidate_id", -1))
        except (TypeError, ValueError):
            continue
        # A hallucinated id must not silently become clip 0.
        if cid < 0 or cid >= len(candidates) or cid in seen:
            continue
        seen.add(cid)

        w = candidates[cid]
        out.append({
            "start_time": round(w.start, 3),
            "end_time": round(w.end, 3),
            "hook_time": round(w.start, 3),
            "topic": str(pick.get("title", ""))[:120] or "Untitled moment",
            "summary": str(pick.get("reason", ""))[:400],
            "reason": str(pick.get("reason", ""))[:400],
            "confidence": min(1.0, max(0.0, _as_int(pick.get("overall"), 70) / 100.0)),
            "transcript_text": w.text,
            "llm_scores": {
                "hook": _as_int(pick.get("hook_strength"), 60),
                "story": _as_int(pick.get("story_completeness"), 60),
                "emotion": _as_int(pick.get("emotional_impact"), 60),
                "shareability": _as_int(pick.get("shareability"), 60),
                "overall": _as_int(pick.get("overall"), 60),
            },
            "signals": w.signals,
        })

        if len(out) >= max_clips:
            break

    return out


def _as_int(value: Any, default: int) -> int:
    try:
        return max(0, min(100, int(float(value))))
    except (TypeError, ValueError):
        return default
