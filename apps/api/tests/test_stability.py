"""
ClipForge AI — System Stability, Health, Diagnostic & Pipeline Tests.
Validates FFmpeg execution, Storage abstraction, Video Probing, Corrupt file rejection,
and End-to-End video processing offline.
"""
from __future__ import annotations

import io
import os
import shutil
from pathlib import Path

import pytest
import shortuuid
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from apps.api.core.config import get_settings
from apps.api.core.database import async_session_factory
from apps.api.core.storage import storage_service
from apps.api.main import app
from apps.api.models.project import Project, Source
from apps.api.models.user import User
from apps.api.models.job import ProcessingJob
from apps.api.video.probe import check_ffmpeg_installation, probe_video, validate_rendered_video
from apps.api.video.renderer import VideoRenderer
from apps.api.schemas.editing_plan import EditingPlan, CropKeyframe, CaptionConfig, AudioConfig
from apps.api.workers.job_runner import _run_pipeline
from scripts.create_test_video import generate_local_test_video

settings = get_settings()


@pytest.fixture(scope="session", autouse=True)
def ensure_sample_video():
    """Ensures a local sample test video exists for offline testing."""
    sample_path = Path("storage/sample_test_video.mp4").resolve()
    if not sample_path.exists() or sample_path.stat().st_size == 0:
        generate_local_test_video(sample_path, duration=5)
    return sample_path


@pytest.fixture
def ensure_speech_video():
    """
    A sample that actually contains speech.

    `sample_test_video.mp4` is a 440 Hz sine tone, so real ASR correctly finds
    nothing in it and the pipeline now (rightly) fails a job with no
    transcript. Anything exercising transcription or clip selection needs
    spoken words, not a tone.
    """
    speech_path = Path("storage/sample_speech_video.mp4").resolve()
    if not speech_path.exists() or speech_path.stat().st_size == 0:
        pytest.skip("storage/sample_speech_video.mp4 missing — run scripts/create_speech_sample.py")
    return speech_path


@pytest.mark.asyncio
async def test_health_diagnostics():
    """Verify that /health and /api/health return ok status for DB, FFmpeg, and Storage."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert data["database"] == "ok"
        assert data["ffmpeg"] == "ok"
        assert data["storage"] == "ok"

        res_api = await ac.get("/api/health")
        assert res_api.status_code == 200
        assert res_api.json()["status"] == "ok"


def test_ffmpeg_and_ffprobe_available():
    """Verify that FFmpeg binary is detected and executable."""
    diag = check_ffmpeg_installation()
    assert diag["status"] == "ok"
    assert "version" in diag
    assert Path(diag["binary_path"]).exists() or diag["binary_path"] == "ffmpeg"


def test_probe_valid_test_video(ensure_sample_video):
    """Verify that FFprobe correctly parses metadata from a valid video."""
    sample_path = ensure_sample_video
    assert sample_path.exists()

    result = probe_video(sample_path)
    assert result.is_valid is True
    assert result.duration > 0
    assert result.width > 0
    assert result.height > 0
    assert result.has_audio is True
    assert result.file_size_bytes > 0


def test_probe_corrupt_file():
    """Verify that FFprobe safely flags a 0-byte or corrupted file as invalid."""
    corrupt_file = Path("storage/temp_corrupt.mp4").resolve()
    corrupt_file.write_bytes(b"NOT_A_REAL_MP4_HEADER")

    try:
        result = probe_video(corrupt_file)
        assert result.is_valid is False
    finally:
        if corrupt_file.exists():
            corrupt_file.unlink()


def test_storage_service_operations():
    """Verify centralized StorageService save, get, exists, and delete methods."""
    test_content = b"TEST_VIDEO_PAYLOAD_12345"
    project_id = "test_proj_storage"

    saved_path, size = storage_service.save_upload(test_content, project_id, "test_clip.mp4")
    assert saved_path.exists()
    assert size == len(test_content)
    assert storage_service.exists(saved_path) is True

    resolved = storage_service.get_file(saved_path)
    assert resolved is not None and resolved.exists()

    # Delete
    deleted = storage_service.delete(saved_path)
    assert deleted is True
    assert storage_service.exists(saved_path) is False


@pytest.mark.asyncio
async def test_video_upload_and_validation(ensure_sample_video):
    """Test uploading an actual video file to the project endpoint."""
    sample_path = ensure_sample_video
    video_bytes = sample_path.read_bytes()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Create project
        proj_res = await ac.post("/api/projects", json={"name": "Upload Test Project"})
        assert proj_res.status_code == 201
        proj_id = proj_res.json()["id"]

        # Upload valid MP4
        files = {"file": ("test_upload.mp4", video_bytes, "video/mp4")}
        upload_res = await ac.post(f"/api/projects/{proj_id}/upload", files=files)
        assert upload_res.status_code == 201
        source_data = upload_res.json()
        assert source_data["source_type"] == "upload"
        assert source_data["file_size"] == len(video_bytes)


@pytest.mark.asyncio
async def test_reject_invalid_file_upload():
    """Verify that uploading invalid extensions is rejected with HTTP 400."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        proj_res = await ac.post("/api/projects", json={"name": "Reject Invalid Ext Project"})
        proj_id = proj_res.json()["id"]

        # Upload .txt file
        files = {"file": ("payload.txt", b"plain text", "text/plain")}
        upload_res = await ac.post(f"/api/projects/{proj_id}/upload", files=files)
        assert upload_res.status_code == 400
        assert "Unsupported file extension" in upload_res.json()["detail"]


def test_video_renderer_execution_and_validation(ensure_sample_video):
    """Verify that VideoRenderer executes an EditingPlan and produces a valid 1080x1920 MP4."""
    source_path = ensure_sample_video
    output_path = Path("storage/processed/test_rendered_output.mp4").resolve()

    plan = EditingPlan(
        clip_id="test_render_unit",
        variant_label="A",
        source_start_time=0.0,
        source_end_time=3.0,
        target_duration=3.0,
        target_width=1080,
        target_height=1920,
        crop_keyframes=[CropKeyframe(time=0.0, zoom=1.0)],
        captions=CaptionConfig(style="clean", burn_captions=False),
        burn_captions=False,
        audio=AudioConfig(normalize=True, compression=True),
    )

    renderer = VideoRenderer()
    success = renderer.render(
        input_source_path=source_path,
        output_mp4_path=output_path,
        plan=plan,
        is_raw_preview=True,
    )
    assert success is True
    assert output_path.exists() and output_path.stat().st_size > 0

    # Validate output with automated post-render validation
    is_valid, reason = validate_rendered_video(output_path, min_duration=1.0)
    assert is_valid is True, f"Rendered video validation failed: {reason}"


@pytest.mark.asyncio
async def test_end_to_end_pipeline_offline(ensure_speech_video):
    """Verify that the full 8-stage pipeline runs completely offline using local test video."""
    sample_path = ensure_speech_video

    async with async_session_factory() as db:
        u_res = await db.execute(select(User))
        user = u_res.scalars().first()

        proj_id = shortuuid.uuid()
        proj = Project(id=proj_id, user_id=user.id, name="E2E Offline Stability Test", status="pending")
        db.add(proj)

        src = Source(
            id=shortuuid.uuid(),
            project_id=proj_id,
            source_type="upload",
            file_path=str(sample_path),
            filename="sample_speech_video.mp4",
            file_size=sample_path.stat().st_size,
            status="accepted",
        )
        db.add(src)

        job_id = shortuuid.uuid()
        job = ProcessingJob(
            id=job_id,
            project_id=proj_id,
            job_type="full_pipeline",
            status="queued",
            stages_total=8,
        )
        db.add(job)
        await db.commit()

    # Run pipeline
    await _run_pipeline(job_id, proj_id, {})

    async with async_session_factory() as db:
        res = await db.execute(select(ProcessingJob).where(ProcessingJob.id == job_id))
        completed_job = res.scalar_one()
        assert completed_job.status == "completed", f"Job failed with error: {completed_job.error}"
        assert completed_job.progress == 100.0
