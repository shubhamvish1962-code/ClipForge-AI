"""Projects router — CRUD, sources, rights, processing trigger."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

import shortuuid
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.api.core.config import get_settings
from apps.api.core.database import get_db
from apps.api.core.security import get_current_user
from apps.api.models.user import User
from apps.api.models.project import Project, Source, RightsRecord
from apps.api.models.clip import CandidateClip
from apps.api.schemas.project import (
    AddSourceRequest,
    CreateProjectRequest,
    ProcessProjectRequest,
    ProjectListResponse,
    ProjectResponse,
    RightsConfirmationRequest,
    RightsRecordResponse,
    SourceResponse,
)

router = APIRouter(prefix="/projects", tags=["projects"])
settings = get_settings()


def _project_to_response(project: Project, source_count: int = 0, clip_count: int = 0) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        name=project.name,
        description=project.description,
        status=project.status,
        created_at=project.created_at.isoformat(),
        updated_at=project.updated_at.isoformat(),
        source_count=source_count,
        clip_count=clip_count,
    )


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(
    body: CreateProjectRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = Project(
        id=shortuuid.uuid(),
        user_id=user.id,
        name=body.name,
        description=body.description,
    )
    db.add(project)
    await db.flush()
    return _project_to_response(project)


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    offset: int = 0,
):
    total_q = await db.execute(
        select(func.count()).select_from(Project).where(Project.user_id == user.id)
    )
    total = total_q.scalar() or 0

    result = await db.execute(
        select(Project)
        .where(Project.user_id == user.id)
        .order_by(Project.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    projects = result.scalars().all()
    return ProjectListResponse(
        projects=[_project_to_response(p) for p in projects],
        total=total,
    )


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_user_project(project_id, user.id, db)

    src_count = await db.execute(
        select(func.count()).select_from(Source).where(Source.project_id == project_id)
    )
    clip_count = await db.execute(
        select(func.count()).select_from(CandidateClip).where(CandidateClip.project_id == project_id)
    )
    return _project_to_response(project, src_count.scalar() or 0, clip_count.scalar() or 0)


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_user_project(project_id, user.id, db)
    await db.delete(project)


# ── Sources ──────────────────────────────────────────────────────────────────

@router.post("/{project_id}/sources", response_model=SourceResponse, status_code=201)
async def add_source_url(
    project_id: str,
    body: AddSourceRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a URL source to the project."""
    await _get_user_project(project_id, user.id, db)

    if body.source_type == "url" and not body.url:
        raise HTTPException(400, "URL is required for URL source type")

    source = Source(
        id=shortuuid.uuid(),
        project_id=project_id,
        source_type=body.source_type,
        url=body.url,
        status="accepted",
    )
    db.add(source)
    await db.flush()
    return SourceResponse(
        id=source.id,
        source_type=source.source_type,
        url=source.url,
        filename=source.filename,
        file_size=source.file_size,
        status=source.status,
        created_at=source.created_at.isoformat(),
    )


@router.post("/{project_id}/upload", response_model=SourceResponse, status_code=201)
async def upload_source(
    project_id: str,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a video file as a source with rigorous probe validation."""
    await _get_user_project(project_id, user.id, db)
    from apps.api.core.storage import storage_service
    from apps.api.video.probe import probe_video

    filename = file.filename or "video.mp4"
    ext = Path(filename).suffix.lower()
    allowed_exts = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
    if ext not in allowed_exts:
        raise HTTPException(400, f"Unsupported file extension '{ext}'. Allowed: {', '.join(allowed_exts)}")

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(400, "Uploaded file is empty (0 bytes)")

    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(400, f"File size exceeds maximum limit of {settings.max_upload_size_mb} MB")

    # Save via centralized storage service
    saved_path, file_size = storage_service.save_upload(content, project_id, filename)

    # Validate that saved file is actually readable video
    probe = probe_video(saved_path)
    if not probe.is_valid:
        storage_service.delete(saved_path)
        raise HTTPException(400, f"Uploaded file is not a valid or readable video stream: {probe.error or 'Decoding failed'}")

    source = Source(
        id=shortuuid.uuid(),
        project_id=project_id,
        source_type="upload",
        filename=filename,
        file_path=str(saved_path),
        file_size=file_size,
        mime_type=file.content_type or "video/mp4",
        status="accepted",
    )
    db.add(source)
    await db.flush()

    return SourceResponse(
        id=source.id,
        source_type=source.source_type,
        url=None,
        filename=source.filename,
        file_size=source.file_size,
        status=source.status,
        created_at=source.created_at.isoformat(),
    )


# ── Rights Confirmation ──────────────────────────────────────────────────────

@router.post("/{project_id}/rights", response_model=RightsRecordResponse, status_code=201)
async def confirm_rights(
    project_id: str,
    body: RightsConfirmationRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_user_project(project_id, user.id, db)

    record = RightsRecord(
        id=shortuuid.uuid(),
        project_id=project_id,
        user_id=user.id,
        content_type=body.content_type,
        confirmation_text=body.confirmation_text,
        confirmed=body.confirmed,
        confirmed_at=datetime.now(timezone.utc) if body.confirmed else None,
    )
    db.add(record)
    await db.flush()

    return RightsRecordResponse(
        id=record.id,
        content_type=record.content_type,
        confirmation_text=record.confirmation_text,
        confirmed=record.confirmed,
        confirmed_at=record.confirmed_at.isoformat() if record.confirmed_at else None,
    )


# ── Processing ───────────────────────────────────────────────────────────────

@router.post("/{project_id}/process")
async def process_project(
    project_id: str,
    body: ProcessProjectRequest = ProcessProjectRequest(),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger full pipeline processing for the project."""
    project = await _get_user_project(project_id, user.id, db)

    # Verify rights confirmed (or auto-confirm for owner)
    rights = await db.execute(
        select(RightsRecord).where(
            RightsRecord.project_id == project_id,
            RightsRecord.confirmed == True,
        )
    )
    if not rights.scalar_one_or_none():
        raise HTTPException(
            403,
            "Content rights not confirmed. Confirm you hold the rights to this "
            "content via POST /projects/{project_id}/rights before processing.",
        )

    # Verify has source
    sources = await db.execute(
        select(Source).where(Source.project_id == project_id, Source.status.in_(["accepted", "pending"]))
    )
    if not sources.scalar_one_or_none():
        raise HTTPException(400, "No accepted source found. Upload or add a valid source first.")

    # Create processing job
    from apps.api.models.job import ProcessingJob

    job = ProcessingJob(
        id=shortuuid.uuid(),
        project_id=project_id,
        job_type="full_pipeline",
        status="queued",
        current_stage="queued",
    )
    db.add(job)
    project.status = "processing"
    await db.flush()

    # Enqueue pipeline
    from apps.api.workers.job_runner import enqueue_job

    await enqueue_job(job.id, project_id, body.model_dump())

    return {"job_id": job.id, "status": "queued", "message": "Processing started"}


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _get_user_project(project_id: str, user_id: str, db: AsyncSession) -> Project:
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        result = await db.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(404, "Project not found")
    return project
