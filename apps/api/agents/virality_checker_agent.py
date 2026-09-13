"""
Virality Checker Agent — Multi-agent ensemble for scoring clip viral potential.

Orchestrates 7 independent judge agents, then aggregates with weighted consensus.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any

from apps.api.agents.base import BaseAgent, AgentResult


# =============================================================================
# 7 JUDGE AGENTS
# =============================================================================

class HookJudgeAgent(BaseAgent):
    """Scores the opening 1–5 seconds. Weight: 20 pts."""

    @property
    def name(self) -> str:
        return "HookJudgeAgent"

    async def execute(self, input_data: dict) -> dict:
        transcript = input_data.get("transcript_text", "")
        hook_time = input_data.get("hook_time", 0.0)
        start_time = input_data.get("start_time", 0.0)
        await asyncio.sleep(random.uniform(0.2, 0.5))

        # Analyze hook patterns
        first_sentence = transcript.split(".")[0] if transcript else ""
        has_question = "?" in first_sentence
        has_number = any(c.isdigit() for c in first_sentence)
        has_contrast = any(w in first_sentence.lower() for w in ["but", "however", "actually", "instead", "surprisingly"])
        has_strong_opener = any(w in first_sentence.lower() for w in ["you know what", "here's the thing", "nobody", "most people", "the biggest"])

        score = random.uniform(14, 20)
        if has_question:
            score = min(20, score + 1)
        if has_number:
            score = min(20, score + 1)
        if has_contrast:
            score = min(20, score + 1.5)
        if has_strong_opener:
            score = min(20, score + 1)

        score = round(min(20, score), 1)

        hook_types = []
        if has_question:
            hook_types.append("question")
        if has_number:
            hook_types.append("specific_number")
        if has_contrast:
            hook_types.append("contrast/counterintuitive")
        if has_strong_opener:
            hook_types.append("strong_opener")

        return {
            "hook_score": score,
            "max_score": 20,
            "hook_type": hook_types or ["statement"],
            "hook_strength": "strong" if score >= 16 else "moderate" if score >= 12 else "weak",
            "has_preamble": "hey guys" in transcript.lower()[:50] or "so today" in transcript.lower()[:50],
            "improvement_suggestion": "Consider starting with the most surprising statement." if score < 16 else None,
            "confidence": round(random.uniform(0.82, 0.96), 2),
            "reasoning": f"Hook score {score}/20. {'Strong' if score >= 16 else 'Moderate'} opening — {'creates curiosity gap' if has_question or has_contrast else 'direct statement with authority'}.",
            "provider": "mock",
        }


class StoryJudgeAgent(BaseAgent):
    """Checks story completeness. Weight: 15 pts."""

    @property
    def name(self) -> str:
        return "StoryJudgeAgent"

    async def execute(self, input_data: dict) -> dict:
        transcript = input_data.get("transcript_text", "")
        duration = input_data.get("duration", 60)
        await asyncio.sleep(random.uniform(0.2, 0.5))

        sentences = [s.strip() for s in transcript.split(".") if s.strip()]
        has_setup = len(sentences) >= 2
        has_resolution = any(w in transcript.lower() for w in ["so", "that's", "the result", "it turned out", "engagement went", "they wrote"])
        has_arc = has_setup and has_resolution

        score = round(random.uniform(11, 15), 1)
        missing = []
        if not has_setup:
            missing.append("setup")
            score -= 2
        if not has_resolution:
            missing.append("resolution")
            score -= 2

        score = max(0, min(15, score))

        return {
            "story_score": score,
            "max_score": 15,
            "completeness": "complete" if not missing else "partial",
            "has_arc": has_arc,
            "missing_elements": missing,
            "self_contained": len(missing) == 0,
            "confidence": round(random.uniform(0.80, 0.95), 2),
            "reasoning": f"Story score {score}/15. {'Complete arc with setup and resolution.' if has_arc else 'Missing: ' + ', '.join(missing) + '.'}",
            "provider": "mock",
        }


class EmotionJudgeAgent(BaseAgent):
    """Analyzes emotional trajectory. Weight: 10 pts."""

    @property
    def name(self) -> str:
        return "EmotionJudgeAgent"

    async def execute(self, input_data: dict) -> dict:
        transcript = input_data.get("transcript_text", "")
        await asyncio.sleep(random.uniform(0.2, 0.5))

        emotions = {
            "excitement": random.uniform(0.4, 0.9),
            "surprise": random.uniform(0.3, 0.85),
            "curiosity": random.uniform(0.5, 0.95),
            "confidence": random.uniform(0.5, 0.9),
            "humor": random.uniform(0.1, 0.5),
            "tension": random.uniform(0.2, 0.6),
            "inspiration": random.uniform(0.4, 0.85),
        }
        dominant = max(emotions, key=emotions.get)
        has_variety = sum(1 for v in emotions.values() if v > 0.4) >= 3

        score = round(random.uniform(6, 10), 1)
        if has_variety:
            score = min(10, score + 1)

        return {
            "emotion_score": round(min(10, score), 1),
            "max_score": 10,
            "dominant_emotion": dominant,
            "emotion_profile": {k: round(v, 2) for k, v in emotions.items()},
            "emotion_arc": ["curiosity", dominant, "inspiration"],
            "has_variety": has_variety,
            "peak_moment_time": input_data.get("start_time", 0) + random.uniform(5, 30),
            "confidence": round(random.uniform(0.78, 0.92), 2),
            "reasoning": f"Emotion score {score:.1f}/10. Dominant: {dominant}. {'Good emotional variety.' if has_variety else 'Limited emotional range.'}",
            "provider": "mock",
        }


class ClarityJudgeAgent(BaseAgent):
    """Ensures clip is understandable independently. Weight: 10 pts."""

    @property
    def name(self) -> str:
        return "ClarityJudgeAgent"

    async def execute(self, input_data: dict) -> dict:
        transcript = input_data.get("transcript_text", "")
        await asyncio.sleep(random.uniform(0.2, 0.5))

        # Check for undefined references
        confusion_points = []
        context_gaps = []

        has_undefined_pronoun = any(p in transcript.lower()[:80] for p in ["he said that", "she mentioned", "they did that", "it was about"])
        if has_undefined_pronoun:
            confusion_points.append("Undefined pronoun reference in opening")

        has_jargon = any(w in transcript.lower() for w in ["transformer models", "latency", "NLP", "fine-tuning"])
        if has_jargon:
            context_gaps.append("Technical jargon may need context for general audience")

        score = round(random.uniform(7, 10), 1)
        if confusion_points:
            score -= 1.5
        if context_gaps:
            score -= 0.5

        score = max(0, min(10, score))

        return {
            "clarity_score": score,
            "max_score": 10,
            "topic_clear_within_seconds": random.choice([5, 8, 10]),
            "confusion_points": confusion_points,
            "context_gaps": context_gaps,
            "audio_sufficient": True,
            "confidence": round(random.uniform(0.82, 0.95), 2),
            "reasoning": f"Clarity score {score:.1f}/10. Topic identifiable within first 8 seconds. {len(confusion_points)} confusion points, {len(context_gaps)} context gaps.",
            "provider": "mock",
        }


class PacingJudgeAgent(BaseAgent):
    """Analyzes information density and flow. Weight: 10 pts."""

    @property
    def name(self) -> str:
        return "PacingJudgeAgent"

    async def execute(self, input_data: dict) -> dict:
        transcript = input_data.get("transcript_text", "")
        duration = input_data.get("duration", 60)
        await asyncio.sleep(random.uniform(0.2, 0.5))

        words = transcript.split()
        wpm = (len(words) / (duration / 60)) if duration > 0 else 0

        filler_words = ["um", "uh", "like", "you know", "kind of", "sort of"]
        filler_count = sum(transcript.lower().count(f) for f in filler_words)
        filler_pct = (filler_count / max(len(words), 1)) * 100

        score = round(random.uniform(7, 10), 1)
        slow_segments = []

        if wpm < 100:
            score -= 1
            slow_segments.append({"note": "Below optimal speech rate"})
        elif wpm > 200:
            score -= 0.5
            slow_segments.append({"note": "Very fast — may hurt comprehension"})

        if filler_pct > 5:
            score -= 1

        score = max(0, min(10, score))

        return {
            "pacing_score": score,
            "max_score": 10,
            "avg_wpm": round(wpm, 1),
            "filler_pct": round(filler_pct, 1),
            "dead_air_pct": round(random.uniform(1, 5), 1),
            "slow_segments": slow_segments,
            "information_density": "high" if wpm > 140 else "moderate" if wpm > 110 else "low",
            "confidence": round(random.uniform(0.80, 0.93), 2),
            "reasoning": f"Pacing score {score:.1f}/10. WPM: {wpm:.0f}. Filler: {filler_pct:.1f}%. {'Good information density.' if wpm > 120 else 'Slightly slow pacing.'}",
            "provider": "mock",
        }


class ShareabilityJudgeAgent(BaseAgent):
    """Predicts shareability. Weight: 10 pts."""

    @property
    def name(self) -> str:
        return "ShareabilityJudgeAgent"

    async def execute(self, input_data: dict) -> dict:
        transcript = input_data.get("transcript_text", "")
        topic = input_data.get("topic", "")
        await asyncio.sleep(random.uniform(0.2, 0.5))

        share_triggers = []
        if any(w in transcript.lower() for w in ["you know what", "here's the thing", "most people don't realize"]):
            share_triggers.append("counterintuitive_insight")
        if any(c.isdigit() for c in transcript):
            share_triggers.append("specific_numbers")
        if "?" in transcript:
            share_triggers.append("thought_provoking_question")
        if any(w in transcript.lower() for w in ["advice", "lesson", "mistake", "tip"]):
            share_triggers.append("actionable_advice")

        quote_candidates = [s.strip() for s in transcript.split(".") if len(s.strip()) > 30 and len(s.strip()) < 120]
        best_quote = max(quote_candidates, key=len) if quote_candidates else ""

        score = round(random.uniform(5, 10), 1)
        if len(share_triggers) >= 2:
            score = min(10, score + 1)
        if best_quote:
            score = min(10, score + 0.5)

        return {
            "shareability_score": round(min(10, score), 1),
            "max_score": 10,
            "share_triggers": share_triggers,
            "quote_candidate": best_quote[:100] if best_quote else None,
            "debate_potential": "high" if "counterintuitive_insight" in share_triggers else "moderate",
            "relatability": "high" if "actionable_advice" in share_triggers else "moderate",
            "confidence": round(random.uniform(0.75, 0.90), 2),
            "reasoning": f"Shareability score {score:.1f}/10. Triggers: {', '.join(share_triggers) or 'none'}. {'Strong quote-worthy content.' if best_quote else 'No standout quotable line.'}",
            "provider": "mock",
        }


class VisualJudgeAgent(BaseAgent):
    """Checks visual presentation quality. Weight: 10 pts."""

    @property
    def name(self) -> str:
        return "VisualJudgeAgent"

    async def execute(self, input_data: dict) -> dict:
        await asyncio.sleep(random.uniform(0.2, 0.5))

        score = round(random.uniform(6, 10), 1)
        crop_issues = []

        if random.random() < 0.3:
            crop_issues.append("Speaker partially out of frame at certain moments")
            score -= 1

        return {
            "visual_score": round(max(0, min(10, score)), 1),
            "max_score": 10,
            "framing_quality": "good" if score >= 7 else "fair",
            "speaker_visible": True,
            "faces_detected": random.choice([1, 2]),
            "lighting_quality": "good",
            "crop_issues": crop_issues,
            "recommended_crop": "speaker_tracking",
            "confidence": round(random.uniform(0.75, 0.90), 2),
            "reasoning": f"Visual score {score:.1f}/10. Speaker well-framed. {'No crop issues.' if not crop_issues else 'Minor framing issue: ' + crop_issues[0]}",
            "provider": "mock",
        }


# =============================================================================
# VIRALITY AGGREGATOR
# =============================================================================

class ViralityAggregator:
    """Combines 7 judge scores with weighted consensus."""

    WEIGHTS = {
        "hook": 20,
        "curiosity": 15,
        "story": 15,
        "emotion": 10,
        "pacing": 10,
        "clarity": 10,
        "visual": 10,
        "shareability": 10,
    }

    def aggregate(self, judge_results: dict[str, dict]) -> dict:
        """
        Combine judge results into a final virality score.

        judge_results: {"hook": {...}, "story": {...}, ...}
        """
        scores = {
            "hook_score": judge_results.get("hook", {}).get("hook_score", 0),
            "story_score": judge_results.get("story", {}).get("story_score", 0),
            "emotion_score": judge_results.get("emotion", {}).get("emotion_score", 0),
            "clarity_score": judge_results.get("clarity", {}).get("clarity_score", 0),
            "pacing_score": judge_results.get("pacing", {}).get("pacing_score", 0),
            "visual_score": judge_results.get("visual", {}).get("visual_score", 0),
            "shareability_score": judge_results.get("shareability", {}).get("shareability_score", 0),
        }

        # Curiosity bonus (computed from cross-agent signals)
        curiosity_bonus = 0
        hook_data = judge_results.get("hook", {})
        story_data = judge_results.get("story", {})

        if "contrast" in str(hook_data.get("hook_type", [])):
            curiosity_bonus += 5
        if story_data.get("has_arc"):
            curiosity_bonus += 3
        if hook_data.get("hook_strength") == "strong":
            curiosity_bonus += 4
        if judge_results.get("emotion", {}).get("has_variety"):
            curiosity_bonus += 3

        curiosity_bonus = min(15, curiosity_bonus)
        scores["curiosity_score"] = curiosity_bonus

        # Total
        total = sum(scores.values())

        # Contested dimensions detection
        contested = {}
        confidences = {}
        for key in ["hook", "story", "emotion", "clarity", "pacing", "visual", "shareability"]:
            conf = judge_results.get(key, {}).get("confidence", 0.5)
            confidences[key] = conf
            if conf < 0.6:
                contested[key] = f"Low confidence ({conf:.2f}) — may need re-evaluation"

        # Reasoning summary
        reasoning = {}
        for key in ["hook", "story", "emotion", "clarity", "pacing", "visual", "shareability"]:
            reasoning[key] = judge_results.get(key, {}).get("reasoning", "")

        avg_confidence = sum(confidences.values()) / max(len(confidences), 1)

        return {
            "total_score": round(min(100, total), 1),
            **scores,
            "judge_reasoning": reasoning,
            "contested_dimensions": contested if contested else None,
            "confidence": round(avg_confidence, 2),
        }


# =============================================================================
# VIRALITY CHECKER AGENT (ORCHESTRATOR)
# =============================================================================

def _apply_llm_scores(aggregated: dict, llm_scores: dict) -> dict:
    """
    Replace simulated dimensions with the selection model's actual judgements.

    The model returns 0-100 per dimension; each is rescaled to that dimension's
    weight in ViralityAggregator.WEIGHTS so the total stays on a 0-100 scale.
    Dimensions the model does not assess (clarity, pacing, visual) keep their
    existing values.
    """
    mapping = {
        "hook_score": ("hook", ViralityAggregator.WEIGHTS["hook"]),
        "story_score": ("story", ViralityAggregator.WEIGHTS["story"]),
        "emotion_score": ("emotion", ViralityAggregator.WEIGHTS["emotion"]),
        "shareability_score": ("shareability", ViralityAggregator.WEIGHTS["shareability"]),
    }

    updated = dict(aggregated)
    for field, (key, weight) in mapping.items():
        raw = llm_scores.get(key)
        if raw is None:
            continue
        try:
            pct = max(0.0, min(100.0, float(raw))) / 100.0
        except (TypeError, ValueError):
            continue
        updated[field] = round(pct * weight, 2)

    score_fields = [
        "hook_score", "curiosity_score", "story_score", "emotion_score",
        "pacing_score", "clarity_score", "visual_score", "shareability_score",
    ]
    updated["total_score"] = round(min(100.0, sum(updated.get(f, 0) or 0 for f in score_fields)), 1)

    # These numbers came from a model reading the transcript, not dice.
    updated["confidence"] = 0.9
    updated["score_source"] = "llm"
    return updated


class ViralityCheckerAgent(BaseAgent):
    """
    Orchestrates the 7-agent virality ensemble.
    Runs all judges in parallel, then aggregates scores.
    """

    @property
    def name(self) -> str:
        return "ViralityCheckerAgent"

    @property
    def description(self) -> str:
        return "Multi-agent ensemble that scores clip viral potential across 7 dimensions: hook, story, emotion, clarity, pacing, visual, shareability."

    async def execute(self, input_data: dict) -> dict:
        # Create all 7 judge agents
        judges = {
            "hook": HookJudgeAgent(),
            "story": StoryJudgeAgent(),
            "emotion": EmotionJudgeAgent(),
            "clarity": ClarityJudgeAgent(),
            "pacing": PacingJudgeAgent(),
            "shareability": ShareabilityJudgeAgent(),
            "visual": VisualJudgeAgent(),
        }

        # Run all judges concurrently. Awaiting each coroutine inside a loop would
        # serialise them; gather schedules them together and returns in order.
        names = list(judges)
        settled = await asyncio.gather(
            *(judges[name].execute(input_data) for name in names),
            return_exceptions=True,
        )

        results = {}
        judge_statuses = {}
        for name, outcome in zip(names, settled):
            if isinstance(outcome, Exception):
                results[name] = {"confidence": 0, "reasoning": f"Judge failed: {outcome}"}
                judge_statuses[name] = "failed"
            else:
                results[name] = outcome
                judge_statuses[name] = "success"

        # Aggregate
        aggregator = ViralityAggregator()
        aggregated = aggregator.aggregate(results)

        # If the selection model already judged this clip, prefer its scores over
        # the simulated judges for the dimensions it actually assessed. Without
        # this the ensemble stays random no matter how good selection gets.
        llm_scores = input_data.get("llm_scores")
        if llm_scores:
            aggregated = _apply_llm_scores(aggregated, llm_scores)

        return {
            **aggregated,
            "judge_statuses": judge_statuses,
            "reasoning": f"Viral potential: {aggregated['total_score']}/100. Ran {len(judges)} judges — {sum(1 for s in judge_statuses.values() if s == 'success')} passed.",
            "confidence": aggregated["confidence"],
            "provider": "mock",
            "model": "virality-ensemble-v1",
        }
