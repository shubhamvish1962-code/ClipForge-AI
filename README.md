# ClipForge AI 🎬

> **Autonomous AI Video Clipper & Short-Form Content Optimization Platform**

ClipForge AI ingests long-form videos (uploaded files or authorized URLs), performs full multimodal understanding, discovers high-impact moments, scores virality using a 7-agent AI judge ensemble, executes smart 9:16 vertical cropping & caption burn-in, validates quality through 6 automated QA agents with an interactive repair loop, and outputs ranked clips.

---

## Key Features

- **Legal Rights & Authorization Safeguards**: Explicit user rights confirmation before ingestion.
- **Provider Abstraction Layer**: Support for LLM, Speech-to-Text, Vision, and Storage provider swapping without rewrites.
- **7-Agent Virality Ensemble**: Independent judges for Hook, Story, Emotion, Clarity, Pacing, Shareability, and Visual quality with weighted consensus scoring.
- **6 QA Sub-Agents & Repair Loop**: Automated post-edit validation with up to 3 automatic repair retries.
- **Real-Time Stage SSE Progress**: Live Server-Sent Events updating frontend pipeline states.
- **Browser Clip Editor**: Interactive timeline trimmer, caption style selector, and 9:16 crop mode editor.
- **Zero API Key Requirement**: Runs out-of-the-box in **Demo Mode** using simulated providers.

---

## Tech Stack

- **Frontend**: Next.js 14, React, TypeScript, Tailwind CSS, Framer Motion
- **Backend**: FastAPI, Python 3.14, SQLAlchemy 2 (async), Pydantic v2
- **Database**: SQLite (local development) / PostgreSQL (production)
- **Auth**: JWT with PBKDF2-HMAC-SHA256 password security

---

## Quick Start (One-Click Launcher)

Simply double-click `run.bat` or run in Command Prompt:

```cmd
run.bat
```

Or using PowerShell:

```powershell
.\run.ps1
```

This will automatically:
1. Verify / create `.env`
2. Launch the **FastAPI Backend** on `http://localhost:8000` in a dedicated window.
3. Launch the **Next.js Frontend** on `http://localhost:3000` in a dedicated window.

---

## Manual Quick Start

### 1. Backend Setup

```bash
# Copy environment template
cp .env.example .env

# Install Python dependencies
pip install -r apps/api/requirements.txt

# Start backend server
python -m uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 --reload
```

Backend will be live at `http://localhost:8000/api/health`.

### 2. Frontend Setup

```bash
cd apps/web

# Install dependencies
npm install

# Start Next.js dev server
npm run dev
```

Frontend will be live at `http://localhost:3000`.

---

## Testing

Run the full pytest suite for auth, agent pipeline, virality ensemble, and QA repair loop:

```bash
python -m pytest apps/api/tests/ -v
```

---

## Architecture Documentation

- [Architecture Overview](docs/architecture.md)
- [Agent Specifications](docs/agents.md)
