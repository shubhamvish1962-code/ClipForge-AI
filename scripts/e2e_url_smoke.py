"""
End-to-end smoke test for URL (audio-first) ingestion.

Mirrors e2e_smoke.py but exercises a YouTube URL source instead of an upload,
so it proves out: audio-only download, real yt-dlp metadata (no video probe
needed yet), transcription from audio, LLM clip selection, section-only video
download for the approved ranges, and rendering from those small local files.

Usage:  python scripts/e2e_url_smoke.py [youtube_url]
"""
from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

BASE = "http://127.0.0.1:8000/api"
URL = sys.argv[1] if len(sys.argv) > 1 else "https://youtu.be/lI7Fw5HTkZY"
TIMEOUT = 600


def fail(msg: str) -> None:
    print(f"\n  FAIL: {msg}")
    sys.exit(1)


def main() -> None:
    c = httpx.Client(base_url=BASE, timeout=180.0)
    uniq = uuid.uuid4().hex[:8]

    creds = {"username": f"urlsmoke_{uniq}", "email": f"urlsmoke_{uniq}@example.com", "password": "SmokeTest123!"}
    r = c.post("/auth/register", json=creds)
    if r.status_code not in (200, 201):
        fail(f"register -> {r.status_code} {r.text[:200]}")
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    print(f"  1. auth ................. ok ({creds['username']})")

    r = c.post("/projects", json={"name": f"URL Smoke {uniq}", "description": "e2e url"})
    if r.status_code not in (200, 201):
        fail(f"create project -> {r.status_code} {r.text[:200]}")
    pid = r.json()["id"]
    print(f"  2. create project ....... ok ({pid})")

    r = c.post(f"/projects/{pid}/sources", json={"source_type": "url", "url": URL})
    if r.status_code != 201:
        fail(f"add url source -> {r.status_code} {r.text[:300]}")
    print(f"  3. add URL source ....... ok ({URL})")

    r = c.post(f"/projects/{pid}/rights", json={
        "content_type": "licensed", "confirmation_text": "I have rights to process this URL.", "confirmed": True,
    })
    if r.status_code not in (200, 201):
        fail(f"confirm rights -> {r.status_code} {r.text[:200]}")
    print("  4. confirm rights ....... ok")

    r = c.post(f"/projects/{pid}/process", json={})
    if r.status_code != 200:
        fail(f"process -> {r.status_code} {r.text[:300]}")
    job_id = r.json()["job_id"]
    print(f"  5. start pipeline ....... ok (job {job_id})")

    deadline = time.time() + TIMEOUT
    last = ""
    while time.time() < deadline:
        r = c.get(f"/jobs/{job_id}")
        if r.status_code != 200:
            fail(f"job poll -> {r.status_code} {r.text[:200]}")
        j = r.json()
        stage, status, prog = j.get("current_stage"), j.get("status"), j.get("progress")
        line = f"{status}/{stage}/{prog}"
        if line != last:
            print(f"       ... {status:<10} {str(stage):<18} {prog}%")
            last = line
        if status == "completed":
            break
        if status == "failed":
            fail(f"pipeline FAILED at {stage}: {j.get('error')}")
        time.sleep(3)
    else:
        fail(f"pipeline did not finish within {TIMEOUT}s (last: {last})")
    print("  6. pipeline completed ... ok")

    r = c.get(f"/clips?project_id={pid}")
    clips = r.json() if isinstance(r.json(), list) else r.json().get("clips", [])
    approved = [c_ for c_ in clips if c_.get("status") == "approved"]
    needs_review = [c_ for c_ in clips if c_.get("status") == "needs_review"]
    print(f"  7. clips ................ {len(clips)} total, {len(approved)} approved, {len(needs_review)} needs_review")
    if not approved:
        fail("no clip reached approved status")

    from apps.api.video.probe import probe_video

    ok = 0
    for c_ in approved:
        matches = list(Path("storage/processed").glob(f"clip_{c_['id']}_var_A_*.mp4"))
        if not matches:
            print(f"       {c_['id'][:8]}  NO FILE")
            continue
        pr = probe_video(matches[0])
        print(f"       {c_['id'][:8]}  {pr.width}x{pr.height} {pr.duration:.2f}s  {'ok' if pr.is_valid else 'INVALID'}")
        ok += pr.is_valid

    if ok == 0:
        fail("no approved clip rendered a valid file")
    print(f"  8. rendered video ....... ok ({ok}/{len(approved)} valid)")

    print("\n  ALL CHECKS PASSED (audio-first URL ingestion)")


if __name__ == "__main__":
    main()
