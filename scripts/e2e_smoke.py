"""
End-to-end smoke test against a running ClipForge backend.

Drives the real HTTP API exactly as the browser does: register, create project,
upload, confirm rights, process, poll to completion, then assert that clips,
scores and rendered files actually exist.

Usage:  python scripts/e2e_smoke.py
"""
from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path

# Run from anywhere: make the repo root importable for apps.api.*
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

BASE = "http://127.0.0.1:8000/api"
# Prefer the spoken-word fixture: the sine-tone sample has no speech, so real
# ASR correctly returns nothing and clip selection has no input to work with.
_SPEECH = Path("storage/sample_speech_video.mp4")
SAMPLE = _SPEECH if _SPEECH.exists() else Path("storage/sample_test_video.mp4")
TIMEOUT = 300  # seconds to wait for the pipeline


def fail(msg: str) -> None:
    print(f"\n  FAIL: {msg}")
    sys.exit(1)


def main() -> None:
    if not SAMPLE.exists():
        fail(f"sample video missing: {SAMPLE}")

    c = httpx.Client(base_url=BASE, timeout=60.0)
    uniq = uuid.uuid4().hex[:8]

    # 1. Register + login
    creds = {
        "username": f"smoke_{uniq}",
        "email": f"smoke_{uniq}@example.com",
        "password": "SmokeTest123!",
    }
    r = c.post("/auth/register", json=creds)
    if r.status_code not in (200, 201):
        fail(f"register -> {r.status_code} {r.text[:200]}")
    token = r.json().get("access_token")
    if not token:
        r = c.post("/auth/login", json={"username": creds["username"], "password": creds["password"]})
        token = r.json().get("access_token")
    if not token:
        fail("no access token returned")
    c.headers["Authorization"] = f"Bearer {token}"
    print(f"  1. auth ................. ok ({creds['username']})")

    # 2. Create project
    r = c.post("/projects", json={"name": f"Smoke {uniq}", "description": "e2e"})
    if r.status_code not in (200, 201):
        fail(f"create project -> {r.status_code} {r.text[:200]}")
    pid = r.json()["id"]
    print(f"  2. create project ....... ok ({pid})")

    # 3. Upload
    with SAMPLE.open("rb") as fh:
        r = c.post(f"/projects/{pid}/upload", files={"file": (SAMPLE.name, fh, "video/mp4")})
    if r.status_code != 201:
        fail(f"upload -> {r.status_code} {r.text[:300]}")
    print(f"  3. upload ............... ok ({r.json().get('source_type')})")

    # 4. Rights gate: processing must be refused before confirmation
    r = c.post(f"/projects/{pid}/process", json={})
    if r.status_code != 403:
        fail(f"rights gate did NOT block: expected 403, got {r.status_code} {r.text[:200]}")
    print("  4. rights gate blocks ... ok (403 before confirmation)")

    r = c.post(f"/projects/{pid}/rights", json={
        "content_type": "user_uploaded",
        "confirmation_text": "I own this content.",
        "confirmed": True,
    })
    if r.status_code not in (200, 201):
        fail(f"confirm rights -> {r.status_code} {r.text[:200]}")
    print("  5. confirm rights ....... ok")

    # 5. Process
    r = c.post(f"/projects/{pid}/process", json={})
    if r.status_code != 200:
        fail(f"process -> {r.status_code} {r.text[:300]}")
    job_id = r.json()["job_id"]
    print(f"  6. start pipeline ....... ok (job {job_id})")

    # 6. Poll
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
        time.sleep(2)
    else:
        fail(f"pipeline did not finish within {TIMEOUT}s (last: {last})")
    print("  7. pipeline completed ... ok")

    # 7. Verify real output
    r = c.get(f"/clips?project_id={pid}")
    if r.status_code != 200:
        fail(f"list clips -> {r.status_code} {r.text[:200]}")
    payload = r.json()
    clips = payload if isinstance(payload, list) else payload.get("clips", [])
    if not clips:
        fail("pipeline completed but produced zero clips")

    scored = [c_ for c_ in clips if (c_.get("score") or {}).get("total_score")]
    selected = [c_ for c_ in clips if c_.get("is_selected")]
    if not scored:
        fail("clips produced but none carry a virality score")
    if not selected:
        fail("clips scored but none were selected — ranking did not mark a top set")
    print(f"  8. clips ................ ok ({len(clips)} clips, {len(scored)} scored, {len(selected)} selected)")

    # Match this run's own clip ids. A time-window glob picks up leftovers from
    # earlier runs and reports their failures against this one.
    from apps.api.video.probe import probe_video

    approved = [c_ for c_ in clips if c_.get("status") == "approved"]
    if not approved:
        fail("no clip reached approved status")

    ok = invalid = missing = 0
    for c_ in approved:
        matches = list(Path("storage/processed").glob(f"clip_{c_['id']}_var_A_*.mp4"))
        if not matches:
            print(f"       {c_['id'][:8]}  NO FILE")
            missing += 1
            continue
        pr = probe_video(matches[0])
        print(f"       {c_['id'][:8]}  {pr.width}x{pr.height} {pr.duration:.2f}s  "
              f"{'ok' if pr.is_valid else 'INVALID'}")
        ok += pr.is_valid
        invalid += not pr.is_valid

    if missing:
        fail(f"{missing} approved clip(s) have no rendered file")
    if invalid:
        fail(f"{invalid} approved clip(s) rendered without a valid video stream")
    print(f"  9. rendered video ....... ok ({ok}/{len(approved)} approved clips valid)")

    print("\n  ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
