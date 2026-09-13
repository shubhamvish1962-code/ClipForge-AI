# ClipForge AI — Pipeline Workflow

Agent-by-agent map of how a video becomes ranked vertical clips.

Everything below is derived from the code, not the README. Section 7 records the defects
found during this audit and how each was resolved — the diagrams describe the code as it
stands **after** those fixes.

**Source of truth:** `apps/api/workers/job_runner.py` (`_run_pipeline`) is the orchestrator. It runs as a single in-process `asyncio` background task — there is no queue broker.

---

## 1. End-to-end flow

```mermaid
flowchart TD
    subgraph CLIENT["Browser — Next.js"]
        U1["Login / JWT"] --> U2["Create project"]
        U2 --> U3["Add source<br/>upload file or URL"]
        U3 --> U4["POST /projects/:id/process"]
        U5["GET /jobs/:id/stream<br/>SSE progress"]
        U6["Review ranked clips<br/>+ clip editor"]
    end

    U4 --> GATE{"Rights record<br/>confirmed?"}
    GATE -- "no" --> E403["HTTP 403 — abort"]
    GATE -- "yes" --> SRC{"Accepted source<br/>exists?"}
    SRC -- "no" --> E400["HTTP 400 — abort"]
    SRC -- "yes" --> JOB["Create ProcessingJob<br/>status = queued"]
    JOB --> ENQ["enqueue_job<br/>asyncio.create_task"]

    ENQ --> P["_run_pipeline"]

    subgraph PIPE["Pipeline — 8 sequential stages"]
        direction TB
        S1["STAGE 1 · Ingestion<br/>5% to 10%"]
        S2["STAGE 2 · Transcription<br/>15% to 30%"]
        S3["STAGE 3 · Scene Detection<br/>35% to 40%"]
        S4["STAGE 4 · Topic Analysis<br/>45% to 50%"]
        S5["STAGE 5 · Clip Discovery<br/>55% to 65%"]
        S6["STAGE 6 · Virality Scoring<br/>70% to 80%"]
        S7["STAGE 7 · QA + Render<br/>82% to 90%"]
        S8["STAGE 8 · Ranking<br/>92% to 95%"]
        S1 --> S2 --> S3 --> S4 --> S5 --> S6 --> S7 --> S8
    end

    P --> S1
    S8 --> DONE["job.status = completed<br/>progress = 100"]
    DONE --> U6

    PIPE -. "_emit per stage" .-> BUF["_job_events<br/>in-memory buffer"]
    BUF -.-> U5

    PIPE -. "_log_agent_run" .-> AR[("AgentRun table")]

    P -. "any exception" .-> FAIL["job.status = failed<br/>project.status = failed<br/>emit error event"]

    style GATE fill:#f59e0b,color:#000
    style E403 fill:#ef4444,color:#fff
    style FAIL fill:#ef4444,color:#fff
    style DONE fill:#10b981,color:#000
```

---

## 2. Stage detail — which agent runs where

```mermaid
flowchart LR
    subgraph ST1["STAGE 1 · Ingestion"]
        direction TB
        A1["No agent —<br/>direct code"] --> A1b["yt-dlp download if URL<br/>then create Video row"]
        A1b --> A1c["probe_video on the real file<br/>then VideoMetadata<br/>fails the job if unreadable"]
    end

    subgraph ST2["STAGE 2 · Transcription"]
        direction TB
        A2["TranscriptionAgent"] --> A2b["Transcript<br/>+ TranscriptSegment<br/>+ Speaker"]
    end

    subgraph ST3["STAGE 3 · Scenes"]
        direction TB
        A3["SceneDetectionAgent"] --> A3b["Scene rows"]
    end

    subgraph ST4["STAGE 4 · Topics"]
        direction TB
        A4["TopicAnalysisAgent"] --> A4b["Topic<br/>keywords, subtopics,<br/>narrative structure"]
    end

    subgraph ST5["STAGE 5 · Discovery"]
        direction TB
        A5["ClipDiscoveryAgent"] --> A5b["CandidateClip rows<br/>windows rescaled onto the<br/>real video duration"]
    end

    ST1 --> ST2 --> ST3 --> ST4 --> ST5

    A2b -. "segments" .-> A5
    A4b -. "topics" .-> A5
```

Stages 2–5 each run exactly one agent. Stages 6 and 7 are **ensembles** — see below.

---

## 3. Stage 6 — the virality ensemble (7 judges)

Runs **once per candidate clip**, in a loop.

```mermaid
flowchart TD
    IN["CandidateClip<br/>transcript, timing, topic"] --> ORCH["ViralityCheckerAgent<br/>orchestrator"]

    ORCH --> J1["HookJudgeAgent"]
    ORCH --> J2["StoryJudgeAgent"]
    ORCH --> J3["EmotionJudgeAgent"]
    ORCH --> J4["ClarityJudgeAgent"]
    ORCH --> J5["PacingJudgeAgent"]
    ORCH --> J6["ShareabilityJudgeAgent"]
    ORCH --> J7["VisualJudgeAgent"]

    J1 --> AGG["ViralityAggregator"]
    J2 --> AGG
    J3 --> AGG
    J4 --> AGG
    J5 --> AGG
    J6 --> AGG
    J7 --> AGG

    AGG --> CUR["Curiosity bonus<br/>derived, not judged<br/>capped at 15"]
    CUR --> TOT["total_score<br/>capped at 100"]
    AGG --> CON{"any judge<br/>confidence below 0.6?"}
    CON -- "yes" --> FLAG["contested_dimensions<br/>flagged for review"]
    CON -- "no" --> TOT
    FLAG --> TOT
    TOT --> OUT[("ClipScore row")]

    JF["Judge raises?<br/>caught per judge —<br/>scored 0, marked failed,<br/>ensemble continues"]
    JF -.-> AGG

    style CUR fill:#8b5cf6,color:#fff
    style FLAG fill:#f59e0b,color:#000
```

### Weighted consensus

| Dimension | Weight | Produced by |
| --- | --- | --- |
| Hook | 20 | `HookJudgeAgent` |
| Curiosity | 15 | **Aggregator** — derived from hook/story/emotion signals |
| Story | 15 | `StoryJudgeAgent` |
| Emotion | 10 | `EmotionJudgeAgent` |
| Pacing | 10 | `PacingJudgeAgent` |
| Clarity | 10 | `ClarityJudgeAgent` |
| Visual | 10 | `VisualJudgeAgent` |
| Shareability | 10 | `ShareabilityJudgeAgent` |
| **Total** | **100** |  |

**7 judges, 8 scored dimensions.** Curiosity has no judge — the aggregator synthesises it from cross-agent signals: +5 contrast hook, +4 strong hook, +3 story arc, +3 emotional variety.

---

## 4. Stage 7 — variants, AI critic, and the repair loop

Runs **once per candidate clip**.

```mermaid
flowchart TD
    C["CandidateClip"] --> W["Derive word timings<br/>evenly spaced from<br/>transcript text"]
    W --> V["create_variant_editing_plans"]
    V --> V5["5 EditingPlans<br/>A High-Retention Master<br/>B Clean Creator<br/>C Podcast Studio<br/>D Cinematic Narrative<br/>E Cyberpunk Tech"]
    V5 --> VDB[("ClipVariant x5<br/>all status = approved")]

    V5 --> PRIM["Primary = Variant A"]
    PRIM --> LOOP["Attempt 1 of max 3"]

    LOOP --> QA["QualityControlAgent<br/>AI Video Critic"]

    QA --> Q1["TranscriptQA<br/>accuracy 95% or better"]
    QA --> Q2["TimingQA<br/>drift 150ms or less"]
    QA --> Q3["AudioQA<br/>LUFS -16 to -13"]
    QA --> Q4["VisualQA"]
    QA --> Q5["HookQA"]
    QA --> Q6["PlatformQA<br/>must be 1080x1920"]

    Q1 --> GATE{"all 6 passed?"}
    Q2 --> GATE
    Q3 --> GATE
    Q4 --> GATE
    Q5 --> GATE
    Q6 --> GATE

    GATE -- "pass" --> APPROVE["clip.status = approved"]
    GATE -- "fail, attempts left" --> REPAIR["Auto-repair<br/>caption margin to 240<br/>contrast to 1.06"]
    REPAIR --> LOOP
    GATE -- "fail, attempts exhausted" --> FORCE["clip.status = needs_review<br/>revision_count++<br/>not rendered, not selected"]

    APPROVE --> RENDER["VideoRenderer.render<br/>ffmpeg 9:16 crop +<br/>burn-in .ass captions"]
    RENDER --> VAL{"validate_rendered_video<br/>real stream on disk?"}
    VAL -- "yes" --> FILE["storage/processed/<br/>clip_ID_var_A_1080p_balanced.mp4"]
    VAL -- "no" --> FORCE

    style FORCE fill:#f59e0b,color:#000
    style REPAIR fill:#f59e0b,color:#000
    style APPROVE fill:#10b981,color:#000
```

Only **Variant A is rendered to video**. B–E are persisted as database rows describing an intended edit; no file is produced for them.

---

## 5. Stage 8 — ranking

```mermaid
flowchart LR
    IN["All CandidateClips<br/>joined to ClipScore"] --> SORT["ORDER BY<br/>total_score DESC"]
    SORT --> RANK["Assign rank 1 to N<br/>all clips ranked"]
    RANK --> SEL["is_selected = true for the<br/>first 5 with status = approved<br/>needs_review clips excluded"]
    SEL --> OUT["Top 5 surfaced<br/>in the UI"]
```

---

## 6. Agent inventory

Every agent inherits `BaseAgent` (`agents/base.py`) and is invoked through `.run()`, which wraps `.execute()` with up to **3 retries** and returns a uniform `AgentResult` (confidence, reasoning, duration, retry count, provider). Each `.run()` in the pipeline is persisted to the `AgentRun` table, which is what powers the per-agent UI timeline.

| Agent | Stage | Wired in? |
| --- | --- | --- |
| `TranscriptionAgent` | 2 | yes |
| `SceneDetectionAgent` | 3 | yes |
| `TopicAnalysisAgent` | 4 | yes |
| `ClipDiscoveryAgent` | 5 | yes |
| `ViralityCheckerAgent` + 7 judges | 6 | yes |
| `QualityControlAgent` + 6 QA sub-agents | 7 | yes |
| `MetadataAgent` | — | On demand only, via `GET /clips/:id/metadata` — titles, description, hashtags. Not part of the pipeline. |

`HookAgent`, `RetentionAgent`, and `VariantAgent` previously sat in `agents/` with zero
references. They have been deleted.

---

## 7. Defects found, and how they were resolved

These were all present in the original implementation and have since been fixed. They are
kept here because the shared failure mode is worth remembering: **every one of them
converted a failure into a plausible-looking success**, which is why a green test suite did
not surface any of them.

| # | Defect | Resolution |
| --- | --- | --- |
| 1 | `probe_video` fabricated metadata — a hardcoded `duration=30.0` with dimensions guessed from one substring check — whenever `ffprobe` was unavailable. On a 10s 1280x720 file it reported 30.0s 1920x1080. | `get_ffprobe_binary()` resolves `FFPROBE_PATH`, an imageio sibling, or `PATH`, returning `None` if genuinely absent. The fallback now parses real values out of `ffmpeg -i` stderr and returns `is_valid=False` rather than guessing dimensions. |
| 2 | The QA repair loop could not reject. Exhausted retries set `status = "approved"` and incremented `passed_count`; `revision_count` never incremented, so the summary always said "0 need review". | Exhausted repairs now set `needs_review`, increment `revision_count`, and emit the failing check names. |
| 3 | The 7 judges ran sequentially despite a comment claiming parallelism — each coroutine was awaited inside a `for` loop. | Replaced with `asyncio.gather(..., return_exceptions=True)`, preserving per-judge failure isolation. Test suite time halved. |
| 4 | Stage 1 wrote hardcoded metadata (228.0s, 1920x1080, 30fps, h264) for every video, never calling the working `probe.py`. | Stage 1 now probes the real file and derives the aspect ratio; an unreadable source fails the job instead of proceeding on invented numbers. |
| 5 | The rights gate never blocked — a missing `RightsRecord` was auto-created as "Auto-confirmed rights by project owner". | `process_project` now returns **403**. The UI already confirms rights before processing, so the normal flow is unaffected. |
| 6 | If the recorded source path was missing or a stale `.part`, Stage 7 globbed `storage/uploads/*.mp4` and rendered the first file over 1 MB — potentially a different video entirely. | The glob fallback is removed; an unavailable source raises. |
| 7 | The README and `docs/agents.md` claimed 7 QA agents; the code registers 6. | Both corrected to 6. |
| 8 | `ClipDiscoveryAgent`'s candidate windows were hardcoded against a ~228s reference video. On any shorter source every clip started past EOF, so ffmpeg exited 0 while writing a 261-byte streamless MP4 — and the job still reported success. | Candidates are rescaled proportionally onto the real duration, and clips collapsing below 1s are dropped. |
| 9 | Nothing verified render output. `validate_rendered_video()` existed but was never called by the pipeline. | Every render is validated; a clip whose file has no usable stream becomes `needs_review` rather than `approved`. |
| 10 | `is_selected` was computed by ranking but absent from every response schema, so the UI could not identify the top 5. | Added to `CandidateClipResponse` and populated in `_clip_to_response`. |
| Agent | Stage | Wired in? |
| --- | --- | --- |
| `TranscriptionAgent` | 2 | yes |
| `SceneDetectionAgent` | 3 | yes |
| `TopicAnalysisAgent` | 4 | yes |
| `ClipDiscoveryAgent` | 5 | yes |
| `ViralityCheckerAgent` + 7 judges | 6 | yes |
| `QualityControlAgent` + 6 QA sub-agents | 7 | yes |
| `MetadataAgent` | — | On demand only, via `GET /clips/:id/metadata` — titles, description, hashtags. Not part of the pipeline. |
| `HookAgent` | — | **Dead code** — zero references |
| `RetentionAgent` | — | **Dead code** — zero references |
| `VariantAgent` | — | **Dead code** — superseded by `create_variant_editing_plans` |

Defects 8–10 were found only by driving the real API end to end — the unit suite was
green throughout. `scripts/e2e_smoke.py` now covers that path and
asserts on actual artifacts (probe-verified 1080x1920 output) rather than HTTP status codes.

Ranking was also tightened as a consequence of #2: `is_selected` is now granted only to
clips with `status = "approved"`, so a `needs_review` clip can no longer occupy a top-5 slot.

### Still worth knowing

- **`ffprobe` is not installed on this machine.** Metadata therefore comes from the ffmpeg
  stderr parser, which is accurate but reads fewer fields than ffprobe's JSON (no per-stream
  bitrate, no exact channel count beyond mono/stereo). `GET /api/health` reports which path
  is live via `metadata_source`. Installing ffprobe or setting `FFPROBE_PATH` restores the
  richer path with no code change.
- Clips in `storage/processed/` rendered before these fixes were produced under the
  fabricated-metadata code and should not be used to judge current output quality.
