# ClipForge AI — Architecture Overview

## Overview

ClipForge AI is an autonomous, multi-agent video clipping & short-form content optimization platform. It ingests long-form video, extracts transcript and visual signals, discovers potential high-impact moments, scores virality using a 7-agent judge ensemble, executes smart 9:16 vertical cropping & caption styling, performs automated Quality Control with an interactive repair loop, and outputs ranked clips.

---

## High-Level Architecture Diagram

```
                             ┌──────────────────────────────────────┐
                             │           Next.js 14 Web UI           │
                             │  (Dashboard, Wizard, Clips, Editor)  │
                             └──────────────────┬───────────────────┘
                                                │ REST / SSE
                                                ▼
                             ┌──────────────────────────────────────┐
                             │            FastAPI Backend           │
                             │     (Auth, Routers, Database ORM)    │
                             └──────────────────┬───────────────────┘
                                                │ Async Job Queue
                                                ▼
                             ┌──────────────────────────────────────┐
                             │       Pipeline Job Orchestrator      │
                             └──────────────────┬───────────────────┘
                                                │
         ┌──────────────────────────────────────┼──────────────────────────────────────┐
         ▼                                      ▼                                      ▼
┌──────────────────┐                  ┌──────────────────┐                  ┌──────────────────┐
│  Ingestion & STT │                  │ Clip Discovery   │                  │ Virality Ensemble│
│ (Speech Provider)│                  │ (Candidate Engine)│                 │ (7 AI Judges)    │
└──────────────────┘                  └──────────────────┘                  └──────────────────┘
         │                                      │                                      │
         └──────────────────────────────────────┼──────────────────────────────────────┘
                                                ▼
                             ┌──────────────────────────────────────┐
                             │     Quality Control & Repair Loop    │
                             │      (7 QA Agents, Max Retries = 3)  │
                             └──────────────────┬───────────────────┘
                                                ▼
                             ┌──────────────────────────────────────┐
                             │          Final Clip Ranking          │
                             └──────────────────────────────────────┘
```

---

## System Components

### 1. Web Application (`/apps/web`)
- **Next.js 14 (App Router)** with TypeScript & Tailwind CSS.
- Dark-first SaaS UI design system using CSS variables and smooth animations.
- Real-time stage progress display powered by Server-Sent Events (SSE).
- Interactive browser timeline editor (`/clips/[id]/edit`).

### 2. API Backend (`/apps/api`)
- **FastAPI** with async SQLAlchemy ORM.
- **SQLite** for local development (no Docker needed) / **PostgreSQL** for production.
- Token-based JWT authentication (`PBKDF2-HMAC-SHA256`).
- Storage provider abstraction supporting local filesystem and S3-compatible object storage.

### 3. Multi-Agent Engine (`/apps/api/agents`)
- Built on `BaseAgent` class with structured `AgentResult`, confidence scoring, and retry logic.
- **7-Agent Virality Ensemble**:
  1. `HookJudgeAgent` (20 pts)
  2. `StoryJudgeAgent` (15 pts)
  3. `EmotionJudgeAgent` (10 pts)
  4. `ClarityJudgeAgent` (10 pts)
  5. `PacingJudgeAgent` (10 pts)
  6. `ShareabilityJudgeAgent` (10 pts)
  7. `VisualJudgeAgent` (10 pts)
  - `ViralityAggregator`: Combines weighted scores + 15 pt curiosity bonus + flags contested dimensions.
- **7 QA Sub-Agents & Repair Loop**:
  - TranscriptQA, TimingQA, ContextQA, AudioQA, VisualQA, HookQA, PlatformQA.
  - Automatically triggers `EditingAgent` repairs if QA checks fail (up to 3 attempts before marking `needs_review`).
