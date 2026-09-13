# AutoClipper — Comprehensive Bug Audit & Stabilization Tracker

**Date**: 2026-08-15  
**Audit Objective**: Systematic review of backend, frontend, FFmpeg rendering, database, job state transitions, and file storage to ensure 100% stability, runnability, and debuggability.

---

## Bug Registry

| ID | Component | Problem | Error Message / Symptom | Root Cause | Severity | Fix | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **BUG-001** | Pipeline / Worker | Stage 7 Crash | `name 'os' is not defined` | `os` and `Path` modules were used in `job_runner.py` Stage 7 without top-level import. | **CRITICAL** | Added `import os` and `from pathlib import Path` to top-level imports in `job_runner.py`. | **FIXED** |
| **BUG-002** | Audio / Stream Sync | Silent Video Preview | Videos played with no audio track in browser | Intermediate `.f400.mp4.part` DASH video-only stream was selected instead of merged audio+video MP4. | **CRITICAL** | Fixed `yt-dlp` output template and audio filter mapping; explicitly excluded `.f400` and `.part` files. | **FIXED** |
| **BUG-003** | Auth / Demo Mode | 401 Unhandled Rejection | `401 Not authenticated` in browser console on `/clips/[id]` | `get_current_user` threw `HTTPException(401)` when demo user accessed direct link without bearer token. | **HIGH** | Added demo/guest fallback in `security.py`, `_get_user_clip`, and `_get_user_project` when demo mode is active. | **FIXED** |
| **BUG-004** | FFmpeg Filter Graph | Invalid Zoompan Expression | `Undefined constant or missing '(' in 't/12)'` | `PI` constant was referenced in FFmpeg `zoompan` filter where it is not in the evaluation symbol table. | **HIGH** | Replaced with valid frame-based expression `zoompan=z='1.0+0.06*sin(in/30)':...` compatible across all FFmpeg builds. | **FIXED** |
| **BUG-005** | Video Rendering | Missing Subtitle Escape on Windows | Subtitle burn failed with path syntax error on Windows drive colons | FFmpeg `subtitles` filter on Windows treats `:` as a filter delimiter unless escaped (`C\\:/...`). | **HIGH** | Implemented `_escape_filter_path` in `renderer.py` replacing `\` with `/` and escaping drive colons. | **FIXED** |
| **BUG-006** | File Storage | Scattered File Paths | Hardcoded relative storage paths in multiple modules | Lack of a centralized `StorageService` abstraction handling existence checks and OS-agnostic paths. | **HIGH** | Implemented centralized `StorageService` in `apps/api/core/storage.py` with validation and atomic writes. | **FIXED** |
| **BUG-007** | Diagnostics | Incomplete `/health` Endpoint | `/health` only returned basic app version, not validating FFmpeg/Storage/DB | Missing system dependency verification for FFmpeg binary and disk write access. | **MEDIUM** | Upgraded `GET /health` to probe database, FFmpeg binary, FFprobe binary, and local storage read/write. | **FIXED** |
| **BUG-008** | Processing State Machine | Invalid State Transitions | Jobs could become stuck in undefined intermediate states | Need strict state machine enforcement (`QUEUED -> INGESTING -> ANALYZING -> RENDERING -> COMPLETED / FAILED`). | **MEDIUM** | Enforced state transitions in `job_runner.py` and added explicit failure reason logging. | **FIXED** |
| **BUG-009** | Video Analysis | Missing Probe Validation | Failed jobs when video metadata was hardcoded without probing | Lack of FFprobe integration to extract exact FPS, codec, resolution, and audio presence. | **MEDIUM** | Created `VideoProbeService` using `ffprobe` to validate all incoming and rendered MP4 files. | **FIXED** |
| **BUG-010** | Error Propagation | Vague Frontend Error States | "Something went wrong" without diagnostic detail | Frontend catch blocks swallowed backend validation details. | **LOW** | Added detailed error banner displaying the actual backend diagnostic message in `apps/web`. | **FIXED** |

---

## Stabilization Priority Order:
1. **CRITICAL**: Eliminate all runtime exceptions and unhandled crashes (BUG-001, BUG-002).
2. **HIGH**: Storage centralization, FFmpeg argument safety, and demo fallback (BUG-003, BUG-004, BUG-005, BUG-006).
3. **MEDIUM**: Diagnostics (`/health`), FFprobe validation, and strict state transitions (BUG-007, BUG-008, BUG-009).
4. **LOW**: UI polish and error messaging (BUG-010).
