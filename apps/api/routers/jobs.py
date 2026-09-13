"""Jobs router — status polling and SSE stream."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.database import get_db
from apps.api.core.security import get_current_user
from apps.api.models.user import User
from apps.api.models.project import Project
from apps.api.models.job import ProcessingJob, AgentRun
from apps.api.schemas.job import AgentRunResponse, JobResponse

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/project/{project_id}/latest", response_model=JobResponse)
async def get_latest_project_job(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the latest processing job for a project."""
    result = await db.execute(
        select(ProcessingJob)
        .join(Project, ProcessingJob.project_id == Project.id)
        .where(ProcessingJob.project_id == project_id, Project.user_id == user.id)
        .order_by(ProcessingJob.created_at.desc())
    )
    job = result.scalars().first()
    if not job:
        raise HTTPException(404, "No jobs found for this project")
    return _job_response(job)


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    job = await _get_user_job(job_id, user.id, db)
    return _job_response(job)


@router.get("/{job_id}/agents", response_model=list[AgentRunResponse])
async def get_job_agents(
    job_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all agent runs for a job."""
    await _get_user_job(job_id, user.id, db)
    result = await db.execute(
        select(AgentRun).where(AgentRun.job_id == job_id).order_by(AgentRun.started_at)
    )
    runs = result.scalars().all()
    return [
        AgentRunResponse(
            id=r.id,
            agent_name=r.agent_name,
            status=r.status,
            confidence=r.confidence,
            reasoning=r.reasoning,
            provider=r.provider,
            model=r.model,
            duration_ms=r.duration_ms,
            retry_count=r.retry_count,
            error=r.error,
            started_at=r.started_at.isoformat(),
            completed_at=r.completed_at.isoformat() if r.completed_at else None,
        )
        for r in runs
    ]


@router.get("/{job_id}/stream")
async def stream_job_progress(
    job_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """SSE stream for real-time job progress updates."""
    job = await _get_user_job(job_id, user.id, db)

    async def event_generator():
        """Poll job status and emit SSE events."""
        from apps.api.workers.job_runner import get_job_events

        last_stage = ""
        while True:
            if await request.is_disconnected():
                break

            # Re-fetch job
            async with db.begin():
                result = await db.execute(
                    select(ProcessingJob).where(ProcessingJob.id == job_id)
                )
                current_job = result.scalar_one_or_none()

            if not current_job:
                yield _sse("error", {"message": "Job not found"})
                break

            # Emit stage changes
            if current_job.current_stage != last_stage:
                last_stage = current_job.current_stage
                yield _sse("stage", {
                    "stage": current_job.current_stage,
                    "progress": current_job.progress,
                    "status": current_job.status,
                    "stages_completed": current_job.stages_completed,
                })

            # Check for buffered events
            events = get_job_events(job_id)
            for event in events:
                yield _sse(event["event"], event)

            if current_job.status in ("completed", "failed", "cancelled"):
                yield _sse("complete", {
                    "status": current_job.status,
                    "progress": 100 if current_job.status == "completed" else current_job.progress,
                    "error": current_job.error,
                })
                break

            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _sse(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def _job_response(job: ProcessingJob) -> JobResponse:
    return JobResponse(
        id=job.id,
        project_id=job.project_id,
        job_type=job.job_type,
        status=job.status,
        current_stage=job.current_stage,
        progress=job.progress,
        stages_completed=job.stages_completed,
        error=job.error,
        started_at=job.started_at.isoformat() if job.started_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
        created_at=job.created_at.isoformat(),
    )


async def _get_user_job(job_id: str, user_id: str, db: AsyncSession) -> ProcessingJob:
    result = await db.execute(
        select(ProcessingJob)
        .join(Project, ProcessingJob.project_id == Project.id)
        .where(ProcessingJob.id == job_id, Project.user_id == user_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Job not found")
    return job
