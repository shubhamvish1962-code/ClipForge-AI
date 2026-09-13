"""LLM Provider Abstraction + Mock Implementation."""

from __future__ import annotations

import asyncio
import random
from abc import ABC, abstractmethod
from typing import Any, Optional


class BaseLLMProvider(ABC):
    """Abstract LLM provider interface."""

    @abstractmethod
    async def complete(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        json_mode: bool = False,
    ) -> dict:
        """
        Send a completion request.
        Returns: {"text": str, "model": str, "usage": dict}
        """
        ...

    @abstractmethod
    async def analyze(
        self,
        content: str,
        instruction: str,
        schema: Optional[dict] = None,
    ) -> dict:
        """
        Analyze content with an instruction.
        Returns structured output when schema is provided.
        """
        ...


class MockLLMProvider(BaseLLMProvider):
    """
    Mock LLM provider for demo mode.
    Returns realistic-looking but clearly marked demo data.
    """

    async def complete(self, prompt: str, system: str = "", temperature: float = 0.7,
                       max_tokens: int = 4096, json_mode: bool = False) -> dict:
        await asyncio.sleep(random.uniform(0.3, 0.8))  # Simulate latency
        return {
            "text": "[DEMO] This is a mock LLM response.",
            "model": "mock-llm-v1",
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            "is_demo": True,
        }

    async def analyze(self, content: str, instruction: str,
                      schema: Optional[dict] = None) -> dict:
        await asyncio.sleep(random.uniform(0.3, 0.8))
        return {
            "text": "[DEMO] Mock analysis complete.",
            "model": "mock-llm-v1",
            "is_demo": True,
        }


def get_llm_provider() -> BaseLLMProvider:
    """Factory — returns the configured LLM provider."""
    from apps.api.core.config import get_settings
    settings = get_settings()

    if settings.llm_provider == "mock":
        return MockLLMProvider()

    if settings.llm_provider == "gemini":
        from apps.api.providers.llm.gemini import GeminiLLMProvider, GeminiProviderError

        try:
            return GeminiLLMProvider(
                api_key=settings.google_api_key,
                model=settings.gemini_model,
            )
        except GeminiProviderError as e:
            # A missing/invalid key should degrade to demo mode, not take the
            # whole pipeline down.
            import logging

            logging.getLogger("clipforge.llm").warning(
                f"Gemini unavailable, falling back to mock: {e}"
            )
            return MockLLMProvider()

    # Future: OpenAI, Anthropic
    return MockLLMProvider()
