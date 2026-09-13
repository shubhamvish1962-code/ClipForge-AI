# AutoClipper — System Stability & Stabilization Report

**Version**: 0.1.0  
**Status**: STABLE & CERTIFIED  
**Date**: 2026-08-15  

---

## 1. Environment & Runtime

| Component | Specification / Version | Status |
| :--- | :--- | :--- |
| **Operating System** | Windows (x64) | Verified |
| **Python Runtime** | Python 3.14.4 | Verified |
| **Node / Next.js** | Node v22.x / Next.js 16.3.0 (Turbopack) | Verified |
| **Backend Framework** | FastAPI + SQLAlchemy + aiosqlite | Verified |
| **FFmpeg Engine** | FFmpeg 7.1 Essentials (with libass, x264, aac) | Verified |
| **Database** | SQLite (`clipforge.db`) with async session pooling | Verified |
| **Storage Backend** | Local Storage (`./storage/uploads`, `./storage/processed`) | Verified |

---

## 2. Architecture & Stable Core Pipeline

```
USER UPLOAD / YOUTUBE URL
         ↓
  VALIDATE & PROBE (FFprobe stream analysis)
         ↓
  INGESTION & METADATA STORAGE
         ↓
  WHISPER TRANSCRIPTION & WORD TIMESTAMPS
         ↓
  SCENE DETECTION & TOPIC CLUSTERING
         ↓
  VIRAL MOMENT DISCOVERY & SCORING (7 AI Judges)
         ↓
  QUALITY CONTROL & MULTI-VARIANT RENDERING (FFmpeg)
         ↓
  POST-RENDER PROBE VALIDATION
         ↓
  STREAM PREVIEW (1080x1920 MP4) & DIRECT EXPORT
```

---

## 3. Bugs Found & Fixed

| ID | Component | Error / Symptom | Root Cause | Status |
| :--- | :--- | :--- | :--- | :--- |
| **BUG-001** | Pipeline Worker | `name 'os' is not defined` in Stage 7 | Missing top-level imports in `job_runner.py` | **FIXED** |
| **BUG-002** | Audio Sync | Silent video previews | yt-dlp selected `.f400` DASH video-only stream | **FIXED** |
| **BUG-003** | Auth / Demo | `401 Not authenticated` console error | Unhandled rejection on direct clip URL access | **FIXED** |
| **BUG-004** | FFmpeg Graph | `Undefined constant in t/12` zoompan error | Non-standard variable in zoom expression | **FIXED** |
| **BUG-005** | Windows Paths | Subtitle burn failed on drive colon (`C:`) | Unescaped Windows drive letter in FFmpeg filter | **FIXED** |
| **BUG-006** | File Storage | Scattered hardcoded paths | Lack of centralized StorageService abstraction | **FIXED** |
| **BUG-007** | Health Diagnostics | Incomplete `/health` endpoint | Did not probe FFmpeg/FFprobe or disk permissions | **FIXED** |
| **BUG-008** | Video Validation | Missing post-render stream check | No probe verification before marking job complete | **FIXED** |

---

## 4. Feature Flags Configuration

To ensure absolute reliability, experimental features are defaulted to `OFF`, while verified core features are `ON`:

```ini
ENABLE_TRANSCRIPTION=true       # Active: Speech-to-text with word-level timestamps
ENABLE_SMART_CROP=true          # Active: 9:16 Vertical crop with smooth keyframed zooms
ENABLE_DYNAMIC_CAPTIONS=true    # Active: Word-level animated ASS subtitle burn-in
ENABLE_AI_CRITIC=true           # Active: Automated Quality Control inspection
ENABLE_AUTO_REVISION=true       # Active: 3-cycle repair loop on failing metrics
ENABLE_BROLL=false              # Flagged OFF: Experimental cutaways (disabled for stability)
ENABLE_MOTION_GRAPHICS=false    # Flagged OFF: Experimental overlays (disabled for stability)
```

---

## 5. Automated Test Suite Results

```
============================= test session starts =============================
apps/api/tests/test_pipeline.py::test_health_check PASSED                [  7%]
apps/api/tests/test_pipeline.py::test_user_registration_and_login PASSED [ 14%]
apps/api/tests/test_pipeline.py::test_youtube_url_source_pipeline PASSED [ 21%]
apps/api/tests/test_pipeline.py::test_virality_checker_ensemble PASSED   [ 28%]
apps/api/tests/test_pipeline.py::test_quality_control_agent PASSED       [ 35%]
apps/api/tests/test_stability.py::test_health_diagnostics PASSED         [ 42%]
apps/api/tests/test_stability.py::test_ffmpeg_and_ffprobe_available PASSED [ 50%]
apps/api/tests/test_stability.py::test_probe_valid_test_video PASSED     [ 57%]
apps/api/tests/test_stability.py::test_probe_corrupt_file PASSED        [ 64%]
apps/api/tests/test_stability.py::test_storage_service_operations PASSED [ 71%]
apps/api/tests/test_stability.py::test_video_upload_and_validation PASSED [ 78%]
apps/api/tests/test_stability.py::test_reject_invalid_file_upload PASSED [ 85%]
apps/api/tests/test_stability.py::test_video_renderer_execution_and_validation PASSED [ 92%]
apps/api/tests/test_stability.py::test_end_to_end_pipeline_offline PASSED [100%]

============================= 14 passed in 13.05s =============================
```

- **Frontend Type Safety**: `npx tsc --noEmit` $\rightarrow \mathbf{0\ errors}$.

---

## 6. How To Run & Develop

### Start Backend:
```bash
python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
```

### Start Frontend:
```bash
cd apps/web
npm run dev
```

### Run Automated Stability Tests:
```bash
python -m pytest apps/api/tests -v
```

### Generate Offline Test Video:
```bash
python scripts/create_test_video.py
```

---

## 7. How To Debug

1. **Health Diagnostics**:
   ```bash
   curl http://127.0.0.1:8000/health
   ```
2. **Probe Video Streams**:
   ```bash
   python -c "from apps.api.video.probe import probe_video; print(probe_video('storage/uploads/video.mp4'))"
   ```
3. **Database Inspection**:
   Inspect SQLite records in `clipforge.db` directly using any SQLite client or async session queries.
