"""
BaseAgent — Abstract base class for all ClipForge AI agents.

Every agent has:
- clear responsibility
- input / output schema
- confidence score
- structured reasoning (shown in UI)
- failure handling + retry
- run logging
"""

from __future__ import annotations

import time
import traceback
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Optional

import shortuuid
from pydantic import BaseModel, Field

from apps.api.core.config import get_settings


class AgentResult(BaseModel):
    """Standardized output from every agent run."""
    agent_name: str
    status: str = "success"  # success | failed | skipped
    confidence: float = 0.0  # 0.0 – 1.0
    reasoning: str = ""  # Human-readable explanation shown in UI
    output: dict = Field(default_factory=dict)  # Agent-specific payload
    started_at: str = ""
    completed_at: str = ""
    duration_ms: int = 0
    retry_count: int = 0
    provider: str = ""
    model: Optional[str] = None
    error: Optional[str] = None


class BaseAgent(ABC):
    """
    Abstract base class for all AI agents.

    Subclasses must implement:
    - name: str property
    - execute(input_data: dict) -> dict
    """

    MAX_RETRIES: int = 3

    def __init__(self):
        self.settings = get_settings()

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name of this agent."""
        ...

    @property
    def description(self) -> str:
        """Human-readable description."""
        return ""

    @abstractmethod
    async def execute(self, input_data: dict) -> dict:
        """
        Core agent logic. Receives input_data, returns output dict.
        Raise exceptions on failure — the runner handles retries.
        """
        ...

    async def run(self, input_data: dict, max_retries: int | None = None) -> AgentResult:
        """
        Run the agent with retry logic and structured result.
        This is the public entry point — never call execute() directly.
        """
        retries = max_retries or self.MAX_RETRIES
        last_error = None

        for attempt in range(retries):
            start = time.time()
            started_at = datetime.now(timezone.utc)

            try:
                output = await self.execute(input_data)
                elapsed = int((time.time() - start) * 1000)

                return AgentResult(
                    agent_name=self.name,
                    status="success",
                    confidence=output.get("confidence", 0.8),
                    reasoning=output.get("reasoning", ""),
                    output=output,
                    started_at=started_at.isoformat(),
                    completed_at=datetime.now(timezone.utc).isoformat(),
                    duration_ms=elapsed,
                    retry_count=attempt,
                    provider=output.get("provider", self.settings.llm_provider),
                    model=output.get("model"),
                )
            except Exception as e:
                last_error = str(e)
                elapsed = int((time.time() - start) * 1000)

                if attempt < retries - 1:
                    # Log retry and continue
                    continue

                return AgentResult(
                    agent_name=self.name,
                    status="failed",
                    confidence=0.0,
                    reasoning=f"Agent failed after {attempt + 1} attempts: {last_error}",
                    output={},
                    started_at=started_at.isoformat(),
                    completed_at=datetime.now(timezone.utc).isoformat(),
                    duration_ms=elapsed,
                    retry_count=attempt,
                    provider=self.settings.llm_provider,
                    error=last_error,
                )

        # Should never reach here, but safety fallback
        return AgentResult(
            agent_name=self.name,
            status="failed",
            error="Unexpected: no retry attempts executed",
        )
