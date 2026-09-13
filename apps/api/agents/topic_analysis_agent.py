"""
Topic Analysis Agent — Identifies topics, subtopics, keywords, narrative structure.
"""

from __future__ import annotations

import asyncio
import random

from apps.api.agents.base import BaseAgent


class TopicAnalysisAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "TopicAnalysisAgent"

    @property
    def description(self) -> str:
        return "Analyzes the full transcript to extract topics, subtopics, keywords, and narrative structure."

    async def execute(self, input_data: dict) -> dict:
        transcript_text = input_data.get("transcript_text", "")
        await asyncio.sleep(random.uniform(0.5, 1.0))

        return {
            "main_topic": "Building AI Startups",
            "subtopics": [
                "User experience vs technology",
                "Fundraising and investor rejections",
                "Product development philosophy",
                "AI in content creation",
                "Founder mindset and persistence",
            ],
            "keywords": [
                "AI", "startup", "investor", "rejection", "product", "user experience",
                "content creation", "persistence", "fundraising", "problem solving",
            ],
            "audience_categories": ["entrepreneurs", "tech professionals", "startup founders", "AI enthusiasts"],
            "narrative_structure": {
                "type": "interview",
                "arc": "problem → failure → insight → vision",
                "opening": "Hook with contrarian insight about AI products",
                "middle": "Stories of failure and learning",
                "closing": "Vision for the future + actionable advice",
            },
            "sections": [
                {"start": 0.0, "end": 48.3, "topic": "UX vs Technology", "summary": "The importance of user experience over sophisticated technology"},
                {"start": 48.8, "end": 95.0, "topic": "Fundraising Journey", "summary": "47 rejections before getting funded — persistence pays"},
                {"start": 95.5, "end": 142.0, "topic": "Product Philosophy", "summary": "Solving problems vs building features"},
                {"start": 142.5, "end": 195.0, "topic": "AI in Content Creation", "summary": "Vision for eliminating content creation friction"},
                {"start": 195.5, "end": 228.0, "topic": "Advice for Founders", "summary": "Start with problems, not technology"},
            ],
            "confidence": 0.91,
            "reasoning": "Identified 5 major sections with clear narrative arc: contrarian opening → failure stories → product philosophy → vision → advice.",
            "provider": "mock",
            "model": "mock-llm-v1",
        }
