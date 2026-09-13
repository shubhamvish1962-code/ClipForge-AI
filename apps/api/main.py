"""
ClipForge AI — FastAPI Application Entry Point.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from apps.api.core.config import get_settings
from apps.api.core.database import close_db, init_db
from apps.api.routers import auth, projects, clips, jobs

settings = get_settings()

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("clipforge")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    logger.info("🎬 ClipForge AI starting up…")
    logger.info(f"   Mode: {'DEMO' if settings.is_demo else 'PRODUCTION'}")
    logger.info(f"   LLM: {settings.llm_provider}")
    logger.info(f"   Speech: {settings.speech_provider}")
    logger.info(f"   Storage: {settings.storage_backend}")

    await init_db()
    logger.info("   Database initialized")

    yield

    await close_db()
    logger.info("🎬 ClipForge AI shut down")


app = FastAPI(
    title="ClipForge AI",
    description="Autonomous AI Video Clipper & Short-Form Content Optimization Platform",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routers
app.include_router(auth.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(clips.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")


# Health check diagnostics
@app.get("/health")
@app.get("/api/health")
async def health():
    """Comprehensive system health and dependency diagnostic check."""
    from apps.api.core.database import async_session_factory
    from apps.api.video.probe import check_ffmpeg_installation
    from apps.api.core.storage import storage_service
    from sqlalchemy import text

    db_status = "ok"
    try:
        async with async_session_factory() as db:
            await db.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"error: {e}"

    ffmpeg_diag = check_ffmpeg_installation()
    ffmpeg_status = "ok" if ffmpeg_diag.get("status") == "ok" else "error"

    storage_status = "ok"
    try:
        test_file = storage_service.temp_dir / ".health_check.tmp"
        test_file.write_text("ok")
        test_file.unlink()
    except Exception as e:
        storage_status = f"error: {e}"

    all_ok = db_status == "ok" and ffmpeg_status == "ok" and storage_status == "ok"

    return {
        "status": "ok" if all_ok else "degraded",
        "app": settings.app_name,
        "version": "0.1.0",
        "mode": "development" if settings.debug else "production",
        "mock_mode": settings.mock_mode or settings.demo_mode,
        "database": db_status,
        "ffmpeg": ffmpeg_status,
        "ffmpeg_details": ffmpeg_diag,
        "storage": storage_status,
        "redis": "disabled (local asyncio worker)" if not settings.use_redis else "connected",
    }


# Dashboard stats
@app.get("/api/dashboard/stats")
async def dashboard_stats():
    """Quick stats for the dashboard."""
    from sqlalchemy import func, select
    from apps.api.core.database import async_session_factory
    from apps.api.models.project import Project
    from apps.api.models.clip import CandidateClip
    from apps.api.models.job import ProcessingJob

    async with async_session_factory() as db:
        projects_count = (await db.execute(select(func.count()).select_from(Project))).scalar() or 0
        clips_count = (await db.execute(select(func.count()).select_from(CandidateClip))).scalar() or 0
        jobs_active = (await db.execute(
            select(func.count()).select_from(ProcessingJob).where(ProcessingJob.status == "processing")
        )).scalar() or 0

    return {
        "total_projects": projects_count,
        "total_clips": clips_count,
        "active_jobs": jobs_active,
        "is_demo": settings.is_demo,
    }
