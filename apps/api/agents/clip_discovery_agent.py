"""
Clip Discovery Agent — The core intelligence.

Searches transcript + video for strong short-form moments.
Generates candidate clips with structured metadata.
"""

from __future__ import annotations

import asyncio
import logging
import random

from apps.api.agents.base import BaseAgent

logger = logging.getLogger("clipforge.agents.discovery")


class ClipDiscoveryAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "ClipDiscoveryAgent"

    @property
    def description(self) -> str:
        return "Discovers strong short-form moments from transcript, scoring for hooks, stories, insights, and emotional beats."

    async def execute(self, input_data: dict) -> dict:
        segments = input_data.get("segments", [])
        topics = input_data.get("topics", {})

        video_duration = float(input_data.get("video_duration") or 0.0)

        # Preferred path: real selection driven by the transcript.
        real = await _discover_from_transcript(segments, topics)
        if real is not None:
            real["candidates"] = _fit_to_video(
                real["candidates"], video_duration, segments
            )
            real["total_found"] = len(real["candidates"])
            return real

        # Fallback: canned demo windows (no LLM configured, or selection failed).
        await asyncio.sleep(random.uniform(1.0, 2.0))

        # Generate realistic candidate clips based on the demo transcript
        candidates = [
            {
                "start_time": 0.0,
                "end_time": 48.3,
                "hook_time": 0.0,
                "topic": "UX vs Technology",
                "summary": "Founder reveals they threw away 3 months of work on a 95%-accurate AI system because nobody could use it — replaced it with a search bar and got 400% more engagement.",
                "reason": "Strong contrarian hook, complete story arc with surprising twist, actionable insight. Self-contained narrative.",
                "confidence": 0.94,
                "transcript_text": "You know what's interesting about building AI products? Most people think the hard part is the technology, but it's actually understanding what humans actually need...",
            },
            {
                "start_time": 55.5,
                "end_time": 95.0,
                "hook_time": 55.5,
                "topic": "47 Rejections",
                "summary": "47 investor rejections. The 48th investor wrote a check in the meeting — not because of the technology, but because of the founder's obsession with the problem.",
                "reason": "Emotional story with specific numbers, underdog narrative, dramatic payoff. Universal founder experience.",
                "confidence": 0.96,
                "transcript_text": "We got rejected by 47 investors before someone said yes...",
            },
            {
                "start_time": 95.5,
                "end_time": 142.0,
                "hook_time": 102.8,
                "topic": "Features vs Problems",
                "summary": "Nobody cares about transformer models or 50ms latency. The best products eliminate entire categories of problems — like smartphones eliminated cameras, maps, and alarm clocks.",
                "reason": "Strong opinionated statement, memorable framework, concrete analogy. Highly shareable insight.",
                "confidence": 0.92,
                "transcript_text": "They talk about features instead of problems...",
            },
            {
                "start_time": 149.2,
                "end_time": 195.0,
                "hook_time": 149.2,
                "topic": "AI Content Creation Vision",
                "summary": "The future of content creation: AI handles the 80% boring grunt work, humans focus on creative decisions. Right now you need a video editor, copywriter, social media manager — soon you'll need none.",
                "reason": "Timely topic, clear vision statement, relatable pain point, forward-looking. Appeals to broad audience.",
                "confidence": 0.88,
                "transcript_text": "We're working on making content creation effortless...",
            },
            {
                "start_time": 195.5,
                "end_time": 228.0,
                "hook_time": 205.5,
                "topic": "Start With Problems",
                "summary": "Don't build an AI product because AI is cool. Build it because someone is struggling and you can help. Technology is just a tool — impact is what matters.",
                "reason": "Strong closing advice, quotable statement, emotional conviction. Universal wisdom, easily shareable.",
                "confidence": 0.91,
                "transcript_text": "Start with a real problem, not with a technology...",
            },
            {
                "start_time": 15.8,
                "end_time": 48.3,
                "hook_time": 15.8,
                "topic": "95% Accuracy, 0% Usage",
                "summary": "We built an AI recommendation engine with 95% accuracy. Nobody used it. We replaced it with a search bar. Engagement up 400%.",
                "reason": "Punchy version of the UX story. Numbers create curiosity gap. Surprising twist format ideal for short-form.",
                "confidence": 0.90,
                "transcript_text": "Sure. We spent six months building this incredibly sophisticated recommendation engine...",
            },
            {
                "start_time": 78.8,
                "end_time": 118.0,
                "hook_time": 78.8,
                "topic": "From Rejection to Clarity",
                "summary": "47 rejections refined the pitch so much that investor #48 wrote a check in the meeting. Then: the biggest mistake founders make — talking about features instead of problems.",
                "reason": "Combines two powerful moments. Emotional arc from pain to triumph to insight. High retention potential.",
                "confidence": 0.87,
                "transcript_text": "It was brutal. There were days I wanted to quit...",
            },
        ]

        # The candidate windows above are authored against a reference timeline
        # (a ~228s demo video). Rescale them onto the real source so every clip
        # lies inside the file — otherwise ffmpeg seeks past EOF and writes a
        # valid-looking but streamless MP4.
        video_duration = float(input_data.get("video_duration") or 0.0)
        if video_duration > 0:
            candidates = _rescale_candidates(candidates, video_duration)

        return {
            "candidates": candidates,
            "total_found": len(candidates),
            "confidence": 0.91,
            "reasoning": f"Discovered {len(candidates)} strong candidate moments. Top signals: contrarian hooks (2), complete story arcs (3), quotable insights (4), emotional beats (2).",
            "provider": "mock",
            "model": "mock-llm-v1",
        }


async def _discover_from_transcript(segments: list[dict], topics: dict) -> dict | None:
    """
    Real discovery: cheap prefilter over the transcript, then one LLM call.

    Returns None only when no real LLM is configured, so demo mode still works.

    When a real provider *is* configured, every failure raises instead. Falling
    back to the canned demo windows in that case produced the worst possible
    outcome: a music video came back with clips about investor rejections and
    transformer models, captioned from a transcript that was never its own —
    output that looks finished and is entirely fabricated.
    """
    from apps.api.providers.llm.base import get_llm_provider, MockLLMProvider
    from apps.api.agents.clip_selection import (
        MAX_CLIP_SECONDS,
        MIN_CLIP_SECONDS,
        build_candidate_windows,
        prefilter,
        select_with_llm,
    )

    provider = get_llm_provider()
    real_llm = not isinstance(provider, MockLLMProvider)

    if not segments or len(segments) < 2:
        if real_llm:
            raise RuntimeError(
                f"Transcript has only {len(segments or [])} segment(s) — not enough "
                "spoken content to choose clips from."
            )
        return None
    if isinstance(provider, MockLLMProvider):
        return None  # demo mode — use the canned windows

    windows = build_candidate_windows(segments)
    if not windows:
        raise RuntimeError(
            "No stretch of speech fits the clip length bounds "
            f"({int(MIN_CLIP_SECONDS)}-{int(MAX_CLIP_SECONDS)}s) — the source may be "
            "too short or too sparsely spoken."
        )

    candidates = prefilter(windows)
    topic = str(topics.get("main_topic", "")) if isinstance(topics, dict) else ""

    clips = await select_with_llm(candidates, provider, topic=topic)
    if not clips:
        raise RuntimeError(
            "Clip selection did not return usable results from the language model. "
            "Check the log for the underlying error and try again."
        )

    logger.info(
        f"LLM selection: {len(windows)} windows -> {len(candidates)} candidates -> {len(clips)} clips"
    )

    return {
        "candidates": clips,
        "total_found": len(clips),
        "confidence": 0.9,
        "reasoning": (
            f"Scanned {len(windows)} transcript windows, shortlisted {len(candidates)} "
            f"on free signals, and ranked them in a single LLM call to pick {len(clips)}."
        ),
        "provider": "llm",
        "model": "clip-selection-v1",
        "candidates_considered": len(candidates),
    }


def _fit_to_video(
    candidates: list[dict], video_duration: float, segments: list[dict]
) -> list[dict]:
    """
    Guarantee every selected clip lies inside the real file.

    Normally the transcript and the video describe the same timeline and this
    only clamps a rounding overshoot. But while the mock speech provider is in
    use its transcript covers a ~228s demo podcast regardless of the actual
    upload, so clip times can land far past the end. ffmpeg would happily seek
    past EOF and emit a streamless MP4, so rescale in that case instead.
    """
    if video_duration <= 0 or not candidates:
        return candidates

    transcript_span = max(
        (float(s.get("end", 0.0)) for s in segments), default=0.0
    )

    # Transcript materially longer than the video => timelines do not match.
    if transcript_span > video_duration * 1.5:
        scale = video_duration / transcript_span
        logger.warning(
            f"Transcript spans {transcript_span:.0f}s but video is {video_duration:.0f}s; "
            f"rescaling clip times by {scale:.3f}. Real ASR removes the need for this."
        )
    else:
        scale = 1.0

    fitted: list[dict] = []
    for cand in candidates:
        start = max(0.0, float(cand["start_time"]) * scale)
        end = min(video_duration, float(cand["end_time"]) * scale)
        if end - start < MIN_CLIP_DURATION:
            continue

        updated = dict(cand)
        updated["start_time"] = round(start, 3)
        updated["end_time"] = round(end, 3)
        hook = cand.get("hook_time")
        if hook is not None:
            updated["hook_time"] = round(min(max(0.0, float(hook) * scale), end), 3)
        fitted.append(updated)

    return fitted


#: Timeline the hardcoded candidate windows were written against.
REFERENCE_DURATION = 228.0
#: Clips shorter than this are not worth rendering.
MIN_CLIP_DURATION = 1.0


def _rescale_candidates(candidates: list[dict], video_duration: float) -> list[dict]:
    """
    Map candidate windows from the reference timeline onto a real video.

    Proportional scaling keeps the relative spacing of the demo moments while
    guaranteeing `0 <= start < end <= video_duration`. Candidates that collapse
    below MIN_CLIP_DURATION on a very short source are dropped rather than
    emitted as unrenderable slivers.
    """
    scale = video_duration / REFERENCE_DURATION
    rescaled: list[dict] = []

    for cand in candidates:
        start = max(0.0, float(cand["start_time"]) * scale)
        end = min(video_duration, float(cand["end_time"]) * scale)
        if end - start < MIN_CLIP_DURATION:
            continue

        updated = dict(cand)
        updated["start_time"] = round(start, 3)
        updated["end_time"] = round(end, 3)

        hook = cand.get("hook_time")
        if hook is not None:
            updated["hook_time"] = round(min(max(0.0, float(hook) * scale), end), 3)

        rescaled.append(updated)

    return rescaled
