"""Job and agent-run schemas."""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, ConfigDict


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    job_type: str
    status: str
    current_stage: str
    progress: float
    stages_completed: Optional[dict] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    created_at: str


class AgentRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    agent_name: str
    status: str
    confidence: float
    reasoning: str
    provider: str
    model: Optional[str]
    duration_ms: int
    retry_count: int
    error: Optional[str] = None
    started_at: str
    completed_at: Optional[str] = None


class SSEEvent(BaseModel):
    """Server-Sent Event payload."""
    event: str  # stage_start | stage_complete | progress | error | complete
    stage: str = ""
    message: str = ""
    progress: float = 0.0
    data: Optional[dict] = None
