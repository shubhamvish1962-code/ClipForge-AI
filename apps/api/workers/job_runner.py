"""
Job Runner — Async in-process pipeline executor.

Runs the full ClipForge pipeline as a background asyncio task.
In production, this would be replaced with Celery workers.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import shortuuid
from sqlalchemy import select

from apps.api.core.config import get_settings
from apps.api.core.database import async_session_factory
from apps.api.models.job import ProcessingJob, AgentRun
from apps.api.models.project import Project, Source
from apps.api.models.video import Video, VideoMetadata
from apps.api.models.transcript import Transcript, TranscriptSegment, Speaker
from apps.api.models.analysis import Scene, Topic
from apps.api.models.clip import CandidateClip, ClipScore, ClipVariant, QAResult

from apps.api.agents.transcription_agent import TranscriptionAgent
from apps.api.agents.scene_detection_agent import SceneDetectionAgent
from apps.api.agents.topic_analysis_agent import TopicAnalysisAgent
from apps.api.agents.clip_discovery_agent import ClipDiscoveryAgent
from apps.api.agents.virality_checker_agent import ViralityCheckerAgent
from apps.api.agents.quality_control_agent import QualityControlAgent

logger = logging.getLogger(__name__)
settings = get_settings()

#: Floor on usable speech. Below this the transcript describes a video with
#: no real dialogue, and any clips built from it would be guesswork.
MIN_SEGMENTS_FOR_CLIPS = 4
MIN_WORDS_FOR_CLIPS = 40

# In-memory event buffer for SSE
_job_events: dict[str, list[dict]] = defaultdict(list)


def get_job_events(job_id: str) -> list[dict]:
    """Pop buffered SSE events for a job."""
    events = _job_events.pop(job_id, [])
    return events


def _emit(job_id: str, event: str, stage: str = "", message: str = "", progress: float = 0, **extra):
    """Buffer an SSE event for a job."""
    _job_events[job_id].append({
        "event": event,
        "stage": stage,
        "message": message,
        "progress": progress,
        **extra,
    })


async def enqueue_job(job_id: str, project_id: str, params: dict):
    """Start the pipeline as a background task."""
    asyncio.create_task(_run_pipeline(job_id, project_id, params))


async def _run_pipeline(job_id: str, project_id: str, params: dict):
    """Execute the full ClipForge AI pipeline."""

    async with async_session_factory() as db:
        try:
            # Mark job as processing
            result = await db.execute(select(ProcessingJob).where(ProcessingJob.id == job_id))
            job = result.scalar_one()
            job.status = "processing"
            job.started_at = datetime.now(timezone.utc)
            job.current_stage = "ingestion"
            await db.commit()

            # ── STAGE 1: INGESTION ───────────────────────────────────────
            _emit(job_id, "stage_start", "ingestion", "Ingesting video source…", 5)

            source_result = await db.execute(
                select(Source).where(Source.project_id == project_id, Source.status.in_(["accepted", "pending"]))
            )
            source = source_result.scalar_one()

            # Audio-first for URL sources: fetch only the small audio track now
            # (needed for transcription/selection) and defer the full video
            # until Stage 7 knows which time ranges are actually worth having.
            # Real duration/dimensions still come from yt-dlp's own metadata —
            # not hardcoded — so this does not reintroduce fabricated values.
            is_url_source = source.source_type == "url" and bool(source.url)
            video_file_path = source.file_path or ""
            source_info: dict | None = None

            if is_url_source:
                from apps.api.video.ffmpeg import download_audio_only, get_video_info

                uploads_dir = Path("storage/uploads")
                source_info = get_video_info(source.url)
                audio_path = download_audio_only(source.url, uploads_dir, f"proj_{project_id[:8]}")
                if not (audio_path and audio_path.exists()):
                    # Without audio there is nothing to transcribe, and every
                    # later stage would quietly fall back to demo data while
                    # still reporting success. Fail loudly instead.
                    raise RuntimeError(
                        f"Could not download audio for {source.url}. "
                        "Transcription and clip selection cannot proceed."
                    )
                if audio_path and audio_path.exists():
                    # Intentionally NOT written to source.file_path: that field
                    # means "a renderable video for this source", and an audio
                    # track must never be mistaken for one by other readers
                    # (e.g. the clip export path, which already guards against
                    # exactly this with a `.m4a` exclusion).
                    video_file_path = str(audio_path)

            video = Video(
                id=shortuuid.uuid(),
                project_id=project_id,
                source_id=source.id,
                file_path=source.file_path or "",
                status="ingested",
            )
            db.add(video)

            # Video metadata. For uploads this comes from probing the real
            # file; for URL sources there is no video file yet, so it comes
            # from yt-dlp's own info (still real data, just not a local probe).
            from apps.api.video.probe import probe_video

            if is_url_source and source_info and source_info.get("duration"):
                duration = source_info["duration"]
                width, height = source_info["width"], source_info["height"]
                fps = source_info["fps"]
                video_codec, audio_codec, file_size = "unknown", None, 0
            elif not is_url_source:
                probe = probe_video(video_file_path) if video_file_path else None
                if not (probe and probe.is_valid):
                    reason = probe.error if probe else "no source file path on record"
                    raise RuntimeError(f"Could not read video metadata from source: {reason}")
                duration, width, height, fps = probe.duration, probe.width, probe.height, probe.fps
                video_codec, audio_codec = probe.video_codec or "unknown", probe.audio_codec
                file_size = probe.file_size_bytes or source.file_size or 0
            else:
                raise RuntimeError(
                    "Could not read video metadata from source: yt-dlp returned no usable info"
                )

            aspect = f"{width}:{height}"
            if height and abs(width / height - 16 / 9) < 0.01:
                aspect = "16:9"
            elif height and abs(width / height - 9 / 16) < 0.01:
                aspect = "9:16"

            metadata = VideoMetadata(
                id=shortuuid.uuid(),
                video_id=video.id,
                duration=duration,
                width=width,
                height=height,
                fps=fps,
                codec=video_codec,
                audio_codec=audio_codec,
                file_size=file_size,
                aspect_ratio=aspect,
            )

            db.add(metadata)
            await db.commit()

            job.current_stage = "ingestion"
            job.progress = 10
            await db.commit()
            _emit(job_id, "stage_complete", "ingestion", "Video metadata extracted", 10)

            # ── STAGE 2: TRANSCRIPTION ───────────────────────────────────
            _emit(job_id, "stage_start", "transcription", "Transcribing audio…", 15)
            job.current_stage = "transcription"
            await db.commit()

            agent = TranscriptionAgent()
            # Use the resolved path (covers downloaded URL sources, where
            # source.file_path is only populated after ingestion).
            tr_result = await agent.run({"audio_path": video_file_path})
            await _log_agent_run(db, project_id, job_id, tr_result)

            # The transcript is the input to every downstream stage. A failed or
            # empty one does not stop the pipeline on its own — clip selection
            # just falls back to demo windows and the job still reports success,
            # producing clips that have nothing to do with the actual video.
            if tr_result.status == "failed":
                raise RuntimeError(f"Transcription failed: {tr_result.error or 'unknown error'}")
            # Clip selection needs actual spoken content to reason about. A
            # music video or ambient footage transcribes to a word or two,
            # which is not "no transcript" but is far too little to pick
            # moments from — and a bare emptiness check lets it through.
            tr_segments = tr_result.output.get("segments") or []
            tr_words = tr_result.output.get("word_count") or 0
            if len(tr_segments) < MIN_SEGMENTS_FOR_CLIPS or tr_words < MIN_WORDS_FOR_CLIPS:
                raise RuntimeError(
                    f"Not enough speech to build clips — found {tr_words} word(s) in "
                    f"{len(tr_segments)} segment(s). This tool needs a video where "
                    "someone is talking (podcast, interview, commentary). Music "
                    "videos and footage without dialogue cannot be clipped."
                )

            transcript = Transcript(
                id=shortuuid.uuid(),
                project_id=project_id,
                video_id=video.id,
                language=tr_result.output.get("language", "en"),
                full_text=tr_result.output.get("full_text", ""),
                word_count=tr_result.output.get("word_count", 0),
                provider=tr_result.provider,
                model=tr_result.model,
                status="completed",
            )
            db.add(transcript)

            # Save segments
            for seg in tr_result.output.get("segments", []):
                db.add(TranscriptSegment(
                    id=shortuuid.uuid(),
                    transcript_id=transcript.id,
                    start_time=seg["start"],
                    end_time=seg["end"],
                    text=seg["text"],
                    speaker_label=seg.get("speaker"),
                    confidence=seg.get("confidence", 1.0),
                    words=seg.get("words"),
                ))

            # Save speakers
            for sp in tr_result.output.get("speakers", []):
                db.add(Speaker(
                    id=shortuuid.uuid(),
                    project_id=project_id,
                    label=sp["label"],
                    segment_count=sp.get("segment_count", 0),
                    total_duration=sp.get("total_duration", 0),
                ))
            await db.commit()

            job.progress = 30
            await db.commit()
            _emit(job_id, "stage_complete", "transcription", f"Transcript generated: {tr_result.output.get('word_count', 0)} words", 30)

            # ── STAGE 3: SCENE DETECTION ─────────────────────────────────
            _emit(job_id, "stage_start", "scene_detection", "Detecting scenes…", 35)
            job.current_stage = "scene_detection"
            await db.commit()

            scene_agent = SceneDetectionAgent()
            sc_result = await scene_agent.run({"duration": metadata.duration})
            await _log_agent_run(db, project_id, job_id, sc_result)

            for sc in sc_result.output.get("scenes", []):
                db.add(Scene(
                    id=shortuuid.uuid(),
                    project_id=project_id,
                    video_id=video.id,
                    scene_index=sc["scene_index"],
                    start_time=sc["start_time"],
                    end_time=sc["end_time"],
                    scene_type=sc["scene_type"],
                    description=sc.get("description", ""),
                    confidence=sc.get("confidence", 1.0),
                ))
            await db.commit()

            job.progress = 40
            await db.commit()
            _emit(job_id, "stage_complete", "scene_detection", f"{sc_result.output.get('total_scenes', 0)} scenes detected", 40)

            # ── STAGE 4: TOPIC ANALYSIS ──────────────────────────────────
            _emit(job_id, "stage_start", "topic_analysis", "Analyzing topics…", 45)
            job.current_stage = "topic_analysis"
            await db.commit()

            topic_agent = TopicAnalysisAgent()
            tp_result = await topic_agent.run({"transcript_text": transcript.full_text})
            await _log_agent_run(db, project_id, job_id, tp_result)

            db.add(Topic(
                id=shortuuid.uuid(),
                project_id=project_id,
                main_topic=tp_result.output.get("main_topic", ""),
                subtopics=tp_result.output.get("subtopics"),
                keywords=tp_result.output.get("keywords"),
                audience_categories=tp_result.output.get("audience_categories"),
                narrative_structure=tp_result.output.get("narrative_structure"),
                sections=tp_result.output.get("sections"),
                confidence=tp_result.confidence,
            ))
            await db.commit()

            job.progress = 50
            await db.commit()
            _emit(job_id, "stage_complete", "topic_analysis", f"Topics identified: {tp_result.output.get('main_topic', '')}", 50)

            # ── STAGE 5: CLIP DISCOVERY ──────────────────────────────────
            _emit(job_id, "stage_start", "clip_discovery", "Discovering clip candidates…", 55)
            job.current_stage = "clip_discovery"
            await db.commit()

            discovery_agent = ClipDiscoveryAgent()
            disc_result = await discovery_agent.run({
                "segments": tr_result.output.get("segments", []),
                "topics": tp_result.output,
                # Needed so candidate windows land inside the real file.
                "video_duration": metadata.duration,
            })
            await _log_agent_run(db, project_id, job_id, disc_result)

            candidates = []
            # Scores the selection model already produced, carried through so the
            # virality ensemble can use real judgements instead of random ones.
            llm_scores_by_clip: dict[str, dict] = {}
            for cand in disc_result.output.get("candidates", []):
                clip = CandidateClip(
                    id=shortuuid.uuid(),
                    project_id=project_id,
                    video_id=video.id,
                    start_time=cand["start_time"],
                    end_time=cand["end_time"],
                    hook_time=cand.get("hook_time"),
                    duration=cand["end_time"] - cand["start_time"],
                    topic=cand.get("topic", ""),
                    summary=cand.get("summary", ""),
                    reason=cand.get("reason", ""),
                    confidence=cand.get("confidence", 0.0),
                    transcript_text=cand.get("transcript_text", ""),
                    status="candidate",
                )
                db.add(clip)
                candidates.append(clip)
                if cand.get("llm_scores"):
                    llm_scores_by_clip[clip.id] = cand["llm_scores"]
            await db.commit()

            job.progress = 65
            await db.commit()
            _emit(job_id, "stage_complete", "clip_discovery", f"{len(candidates)} candidate moments found", 65)

            # ── STAGE 6: VIRALITY SCORING ────────────────────────────────
            _emit(job_id, "stage_start", "virality_scoring", "Running 7-agent virality ensemble…", 70)
            job.current_stage = "virality_scoring"
            await db.commit()

            virality_agent = ViralityCheckerAgent()
            for i, clip in enumerate(candidates):
                vr = await virality_agent.run({
                    "transcript_text": clip.transcript_text,
                    "start_time": clip.start_time,
                    "end_time": clip.end_time,
                    "hook_time": clip.hook_time,
                    "duration": clip.duration,
                    "topic": clip.topic,
                    "llm_scores": llm_scores_by_clip.get(clip.id),
                })
                await _log_agent_run(db, project_id, job_id, vr)

                score = ClipScore(
                    id=shortuuid.uuid(),
                    candidate_clip_id=clip.id,
                    total_score=vr.output.get("total_score", 0),
                    hook_score=vr.output.get("hook_score", 0),
                    curiosity_score=vr.output.get("curiosity_score", 0),
                    story_score=vr.output.get("story_score", 0),
                    emotion_score=vr.output.get("emotion_score", 0),
                    pacing_score=vr.output.get("pacing_score", 0),
                    clarity_score=vr.output.get("clarity_score", 0),
                    visual_score=vr.output.get("visual_score", 0),
                    shareability_score=vr.output.get("shareability_score", 0),
                    judge_reasoning=vr.output.get("judge_reasoning"),
                    contested_dimensions=vr.output.get("contested_dimensions"),
                    confidence=vr.output.get("confidence", 0),
                    provider=vr.provider,
                )
                db.add(score)

                progress = 70 + (i + 1) / len(candidates) * 10
                _emit(job_id, "progress", "virality_scoring", f"Scored clip {i + 1}/{len(candidates)}", progress)

            await db.commit()

            job.progress = 80
            await db.commit()
            _emit(job_id, "stage_complete", "virality_scoring", "All candidates scored", 80)

            # ── STAGE 7: QUALITY CONTROL & MULTI-VARIANT RENDERING ────────
            _emit(job_id, "stage_start", "quality_control", "Executing AI Video Critic & Post-Production Renderer…", 82)
            job.current_stage = "quality_control"
            await db.commit()

            from apps.api.video.renderer import VideoRenderer
            from apps.api.schemas.editing_plan import create_variant_editing_plans

            qa_agent = QualityControlAgent()
            renderer = VideoRenderer()
            passed_count = 0
            revision_count = 0

            # Source video check. Only this project's own file is acceptable —
            # falling back to an arbitrary upload would render someone else's video.
            # URL sources have no video file yet (audio-first ingestion) — theirs
            # is resolved per-range, right before rendering, once clip times are known.
            source_video_path = video.file_path
            if not is_url_source and (
                not source_video_path or not os.path.exists(source_video_path)
                or source_video_path.endswith(".part")
            ):
                raise RuntimeError(
                    f"Source video unavailable for rendering: {source_video_path or '(no path)'}. "
                    "The download may have failed or the file was removed."
                )

            # Renders are collected here instead of executed inline. The QA
            # repair loop below must stay sequential (it shares the one
            # AsyncSession, which is not safe for concurrent use), but each
            # clip renders at most once *after* QA approves it — so the actual
            # ffmpeg calls have no data dependency on each other and can run
            # concurrently once collected.
            render_jobs: list[dict] = []

            for clip in candidates:
                # 1. Synthesize 5 distinct EditingPlans
                words = []
                if clip.transcript_text:
                    dur = max(1.0, clip.duration)
                    raw_w = clip.transcript_text.strip().split()
                    step = dur / max(1, len(raw_w))
                    for idx, w in enumerate(raw_w):
                        words.append({
                            "word": w,
                            "start": clip.start_time + (idx * step),
                            "end": clip.start_time + ((idx + 1) * step),
                        })

                variant_plans = create_variant_editing_plans(
                    clip_id=clip.id,
                    start_time=clip.start_time,
                    end_time=clip.end_time,
                    transcript_words=words,
                    topic=clip.topic or "Tech & Product",
                )

                # Persist all 5 variants
                for p in variant_plans:
                    db.add(ClipVariant(
                        id=shortuuid.uuid(),
                        candidate_clip_id=clip.id,
                        variant_label=p.variant_label,
                        variant_type=p.variant_name,
                        description=f"{p.variant_name} - {p.captions.style} typography with short-form audio mastering",
                        start_time=p.source_start_time,
                        end_time=p.source_end_time,
                        duration=p.target_duration,
                        caption_style=p.captions.style,
                        crop_mode=p.crop_mode,
                        status="approved",
                    ))
                await db.commit()

                # 2. Run AI Video Critic on Primary Variant with Automatic Revision Loop (Up to 3 Cycles)
                primary_plan = variant_plans[0]
                for attempt in range(settings.qa_max_retries):
                    qa_result = await qa_agent.run({
                        "transcript_text": clip.transcript_text,
                        "duration": clip.duration,
                        "width": 1080,
                        "height": 1920,
                        "variant": "A",
                    })
                    await _log_agent_run(db, project_id, job_id, qa_result)

                    overall_passed = qa_result.output.get("overall_passed", True)

                    if overall_passed:
                        clip.status = "approved"
                        passed_count += 1

                        # Upload sources already have a checked local file
                        # (validated above); URL sources resolve their video
                        # in the section-download step, right before rendering.
                        if is_url_source or (source_video_path and os.path.exists(source_video_path)):
                            processed_dir = Path("storage/processed")
                            processed_dir.mkdir(parents=True, exist_ok=True)
                            out_file = processed_dir / f"clip_{clip.id}_var_A_1080p_balanced.mp4"
                            render_jobs.append({
                                "clip": clip,
                                "plan": primary_plan,
                                "words": words,
                                "out_file": out_file,
                            })
                        break
                    elif attempt < settings.qa_max_retries - 1:
                        # Auto-repair loop: Adjust caption margin and zoom parameters
                        primary_plan.captions.margin_bottom = 240
                        primary_plan.color.contrast = 1.06
                        _emit(job_id, "progress", "quality_control",
                              f"AI Critic auto-repairing {clip.topic} (cycle {attempt + 2})", 85)
                    else:
                        # Repairs exhausted and the critic still rejects it. Flag for
                        # human review instead of approving — otherwise the QA gate
                        # can never reject anything and the counts are meaningless.
                        clip.status = "needs_review"
                        revision_count += 1
                        failed = ", ".join(qa_result.output.get("failed_agents", [])) or "unknown checks"
                        _emit(job_id, "progress", "quality_control",
                              f"{clip.topic or 'Clip'} needs review after "
                              f"{settings.qa_max_retries} repair attempts (failed: {failed})", 88)

                await db.commit()

            # For URL sources, this is the first point the video itself is
            # touched: only the ranges QA actually approved are fetched, not
            # the whole source. Each job is rebased onto its section file's
            # own local timeline (section files start at their own 0:00, not
            # the original video's absolute position).
            if is_url_source and render_jobs:
                from apps.api.video.ffmpeg import download_video_sections

                _emit(job_id, "progress", "quality_control",
                      f"Fetching video for {len(render_jobs)} approved clip range(s)…", 84)

                ranges = [(j["clip"].start_time, j["clip"].end_time) for j in render_jobs]
                sections = download_video_sections(
                    source.url, ranges, Path("storage/uploads"), f"proj_{project_id[:8]}"
                )

                resolved_jobs = []
                for job_spec in render_jobs:
                    clip = job_spec["clip"]
                    section = next(
                        (s for s in sections
                         if s.range_start <= clip.start_time and clip.end_time <= s.range_end),
                        None,
                    )
                    if section is None:
                        clip.status = "needs_review"
                        passed_count -= 1
                        revision_count += 1
                        _emit(job_id, "progress", "quality_control",
                              f"{clip.topic or 'Clip'}: could not fetch video for this range", 87)
                        logger.warning(
                            f"No downloaded section covers clip {clip.id} "
                            f"[{clip.start_time:.1f}-{clip.end_time:.1f}]"
                        )
                        continue

                    # Rebase the seek point onto the section file's own timeline.
                    # target_duration (not source_end_time) drives -t in the
                    # renderer, so only the start offset needs adjusting.
                    plan = job_spec["plan"]
                    plan.source_start_time = section.local_offset(plan.source_start_time)
                    job_spec["source_path"] = str(section.path)
                    resolved_jobs.append(job_spec)

                render_jobs = resolved_jobs
                await db.commit()
            else:
                for job_spec in render_jobs:
                    job_spec["source_path"] = source_video_path

            # ── Render all QA-approved clips concurrently ─────────────────
            # subprocess.run() blocks a thread, not the event loop, so N ffmpeg
            # encodes can genuinely overlap via to_thread. Bounded by
            # max_concurrent_renders — an unbounded burst would oversubscribe
            # CPU cores or exceed the GPU driver's concurrent NVENC session cap.
            if render_jobs:
                _emit(job_id, "progress", "quality_control",
                      f"Rendering {len(render_jobs)} approved clips "
                      f"(up to {settings.max_concurrent_renders} at once)…", 86)

                semaphore = asyncio.Semaphore(settings.max_concurrent_renders)

                async def _render_one(job_spec: dict) -> tuple[dict, bool]:
                    async with semaphore:
                        ok = await asyncio.to_thread(
                            renderer.render,
                            input_source_path=job_spec["source_path"],
                            output_mp4_path=job_spec["out_file"],
                            plan=job_spec["plan"],
                            transcript_words=job_spec["words"],
                            is_raw_preview=False,
                        )
                    return job_spec, ok

                results = await asyncio.gather(*(_render_one(j) for j in render_jobs))

                from apps.api.video.probe import validate_rendered_video

                for job_spec, render_ok in results:
                    clip = job_spec["clip"]
                    out_file = job_spec["out_file"]

                    # ffmpeg can exit 0 while writing a streamless container
                    # (e.g. a requested range outside the source), so a clip
                    # must not be called approved on the render call alone.
                    is_valid, reason = (False, "render did not complete") if not render_ok \
                        else validate_rendered_video(out_file)

                    if not is_valid:
                        clip.status = "needs_review"
                        passed_count -= 1
                        revision_count += 1
                        _emit(job_id, "progress", "quality_control",
                              f"{clip.topic or 'Clip'} render failed validation: {reason}", 88)
                        logger.warning(f"Render validation failed for clip {clip.id}: {reason}")

                await db.commit()

            job.progress = 90
            await db.commit()
            _emit(job_id, "stage_complete", "quality_control",
                  f"{passed_count} clips passed, {revision_count} need review", 90)

            # ── STAGE 8: RANKING ─────────────────────────────────────────
            _emit(job_id, "stage_start", "ranking", "Ranking final clips…", 92)
            job.current_stage = "ranking"
            await db.commit()

            # Rank by total_score descending
            scored_clips = await db.execute(
                select(CandidateClip, ClipScore)
                .join(ClipScore, ClipScore.candidate_clip_id == CandidateClip.id)
                .where(CandidateClip.project_id == project_id)
                .order_by(ClipScore.total_score.desc())
            )
            # Rank everything, but only auto-select clips that actually cleared QA.
            selected = 0
            for rank, (clip, score) in enumerate(scored_clips.all(), 1):
                clip.rank = rank
                if clip.status == "approved" and selected < 5:
                    clip.is_selected = True
                    selected += 1
                else:
                    clip.is_selected = False

            await db.commit()

            job.progress = 95
            await db.commit()
            _emit(job_id, "stage_complete", "ranking", "Final ranking complete", 95)

            # ── COMPLETE ─────────────────────────────────────────────────
            job.status = "completed"
            job.progress = 100
            job.current_stage = "complete"
            job.completed_at = datetime.now(timezone.utc)

            project_result = await db.execute(select(Project).where(Project.id == project_id))
            project = project_result.scalar_one()
            project.status = "completed"

            await db.commit()
            _emit(job_id, "complete", "complete", "Processing complete!", 100)

        except Exception as e:
            logger.exception(f"Pipeline failed for job {job_id}")
            try:
                result = await db.execute(select(ProcessingJob).where(ProcessingJob.id == job_id))
                job = result.scalar_one()
                job.status = "failed"
                job.error = str(e)[:1000]
                job.completed_at = datetime.now(timezone.utc)

                p_result = await db.execute(select(Project).where(Project.id == project_id))
                project = p_result.scalar_one()
                project.status = "failed"
                await db.commit()
            except Exception:
                pass
            _emit(job_id, "error", "pipeline", f"Processing failed: {str(e)[:200]}", 0)


async def _log_agent_run(db, project_id: str, job_id: str, result):
    """Log an agent run to the database."""
    run = AgentRun(
        id=shortuuid.uuid(),
        project_id=project_id,
        job_id=job_id,
        agent_name=result.agent_name,
        status=result.status,
        confidence=result.confidence,
        reasoning=result.reasoning,
        provider=result.provider,
        model=result.model,
        duration_ms=result.duration_ms,
        retry_count=result.retry_count,
        error=result.error,
        started_at=datetime.fromisoformat(result.started_at) if result.started_at else datetime.now(timezone.utc),
        completed_at=datetime.fromisoformat(result.completed_at) if result.completed_at else None,
    )
    db.add(run)
    await db.flush()
