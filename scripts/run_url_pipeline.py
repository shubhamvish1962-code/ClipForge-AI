"""
Run the full pipeline for a URL source in this process.

The HTTP path spawns the pipeline as an in-process asyncio task on the uvicorn
worker, so the job dies silently if that server is restarted — it just sits at
whatever stage it reached, still marked "processing". Driving `_run_pipeline`
directly keeps the work tied to this script instead.

Usage:  python scripts/run_url_pipeline.py [url]
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import shortuuid
from sqlalchemy import select

from apps.api.core.database import async_session_factory
from apps.api.models.job import ProcessingJob
from apps.api.models.project import Project, Source, RightsRecord
from apps.api.models.user import User
from apps.api.models.clip import CandidateClip
from apps.api.workers.job_runner import _run_pipeline

URL = sys.argv[1] if len(sys.argv) > 1 else "https://youtu.be/lI7Fw5HTkZY"


async def main() -> None:
    from datetime import datetime, timezone

    async with async_session_factory() as db:
        user = (await db.execute(select(User))).scalars().first()
        if not user:
            sys.exit("No user in DB — run the e2e smoke test once to create one.")

        pid = shortuuid.uuid()
        db.add(Project(id=pid, user_id=user.id, name="URL pipeline run", status="pending"))
        db.add(Source(id=shortuuid.uuid(), project_id=pid, source_type="url",
                      url=URL, status="accepted"))
        db.add(RightsRecord(id=shortuuid.uuid(), project_id=pid, user_id=user.id,
                            content_type="licensed", confirmation_text="verified run",
                            confirmed=True, confirmed_at=datetime.now(timezone.utc)))
        jid = shortuuid.uuid()
        db.add(ProcessingJob(id=jid, project_id=pid, job_type="full_pipeline",
                             status="queued", stages_total=8))
        await db.commit()

    print(f"project={pid} job={jid}\nurl={URL}\nrunning…", flush=True)
    await _run_pipeline(jid, pid, {})

    async with async_session_factory() as db:
        job = (await db.execute(select(ProcessingJob).where(ProcessingJob.id == jid))).scalar_one()
        print(f"\nstatus={job.status} stage={job.current_stage} error={job.error or '-'}", flush=True)

        clips = (await db.execute(
            select(CandidateClip).where(CandidateClip.project_id == pid)
            .order_by(CandidateClip.rank)
        )).scalars().all()

        print(f"\n{len(clips)} clips:", flush=True)
        for c in clips:
            print(f"  {c.status:<13} {c.start_time:7.1f}-{c.end_time:7.1f}s "
                  f"({c.end_time - c.start_time:5.1f}s)  {(c.topic or '')[:50]}", flush=True)

        from apps.api.video.probe import probe_video
        ok = 0
        approved = [c for c in clips if c.status == "approved"]
        print("\nrendered:", flush=True)
        for c in approved:
            m = list(Path("storage/processed").glob(f"clip_{c.id}_var_A_*.mp4"))
            if not m:
                print(f"  {c.id[:8]}  NO FILE", flush=True)
                continue
            p = probe_video(m[0])
            ok += p.is_valid
            print(f"  {c.id[:8]}  {p.width}x{p.height} {p.duration:6.2f}s  "
                  f"{'ok' if p.is_valid else 'INVALID'}  {m[0].stat().st_size/1048576:.0f}MB", flush=True)
        print(f"\n{ok}/{len(approved)} approved clips valid", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
