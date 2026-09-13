"""
Google AI Studio (Gemini) LLM provider.

Uses the REST endpoint directly rather than the google-generativeai SDK so the
project keeps a single HTTP dependency and stays easy to swap out. Calls run in
a thread so they do not block the pipeline's event loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.request
from typing import Any, Optional

from apps.api.providers.llm.base import BaseLLMProvider

logger = logging.getLogger("clipforge.llm.gemini")

API_ROOT = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProviderError(RuntimeError):
    """Raised when Gemini cannot produce a usable response."""


class GeminiLLMProvider(BaseLLMProvider):
    """Gemini-backed provider. Supports JSON-mode structured output."""

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash", timeout: int = 90):
        if not api_key:
            raise GeminiProviderError("Gemini API key is empty")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout

    # ── internals ────────────────────────────────────────────────────────

    def _post(self, payload: dict) -> dict:
        url = f"{API_ROOT}/models/{self._model}:generateContent?key={self._api_key}"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            # Never let the key reach logs or error messages.
            detail = e.read().decode("utf-8", "replace")[:400].replace(self._api_key, "***")
            raise GeminiProviderError(f"Gemini HTTP {e.code}: {detail}") from None
        except Exception as e:
            raise GeminiProviderError(
                f"Gemini request failed: {str(e).replace(self._api_key, '***')[:300]}"
            ) from None

    @staticmethod
    def _extract_text(data: dict) -> str:
        try:
            parts = data["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts)
        except (KeyError, IndexError):
            blocked = (data.get("promptFeedback") or {}).get("blockReason")
            if blocked:
                raise GeminiProviderError(f"Gemini blocked the prompt: {blocked}")
            raise GeminiProviderError("Gemini returned no candidates")

    async def _generate(
        self,
        prompt: str,
        system: str,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> dict:
        payload: dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        if json_mode:
            payload["generationConfig"]["responseMimeType"] = "application/json"
            # Gemini 2.5 spends "thinking" tokens out of the same maxOutputTokens
            # budget as the answer. On a large prompt that silently truncates the
            # JSON mid-object, which surfaces only as a parse error. Structured
            # extraction does not benefit from thinking, so switch it off and
            # leave the whole budget for the response.
            payload["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 0}

        data = await asyncio.to_thread(self._post, payload)

        finish = (data.get("candidates") or [{}])[0].get("finishReason")
        if finish == "MAX_TOKENS":
            raise GeminiProviderError(
                f"Gemini hit the {max_tokens}-token output cap; the response was "
                "truncated. Raise max_tokens or shorten the prompt."
            )

        text = self._extract_text(data)
        usage = data.get("usageMetadata", {})

        return {
            "text": text,
            "model": self._model,
            "usage": {
                "prompt_tokens": usage.get("promptTokenCount", 0),
                "completion_tokens": usage.get("candidatesTokenCount", 0),
            },
            "is_demo": False,
        }

    # ── BaseLLMProvider ──────────────────────────────────────────────────

    async def complete(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        json_mode: bool = False,
    ) -> dict:
        return await self._generate(prompt, system, temperature, max_tokens, json_mode)

    async def analyze(
        self,
        content: str,
        instruction: str,
        schema: Optional[dict] = None,
    ) -> dict:
        prompt = f"{instruction}\n\n---\n{content}"
        if schema:
            prompt += (
                "\n\n---\nRespond with JSON matching exactly this schema:\n"
                f"{json.dumps(schema, indent=2)}"
            )

        result = await self._generate(
            prompt, system="", temperature=0.2, max_tokens=32768, json_mode=bool(schema)
        )

        if schema:
            result["parsed"] = _parse_json(result["text"])
        return result


def _parse_json(text: str) -> Any:
    """
    Parse a JSON payload from model output.

    JSON mode normally returns clean JSON, but a fenced ```json block still shows
    up occasionally; strip it rather than failing the whole pipeline over syntax.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1:
            start, end = cleaned.find("["), cleaned.rfind("]")
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError:
                pass
        raise GeminiProviderError(f"Could not parse JSON from response: {cleaned[:200]}")
