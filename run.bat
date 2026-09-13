@echo off
title ClipForge AI Launcher
cls
echo =======================================================================
echo                 🎬 ClipForge AI — One-Click Launcher
echo =======================================================================
echo.

if not exist .env (
    echo [.env] Creating environment file from .env.example...
    copy .env.example .env >nul
)

echo [1/2] Starting FastAPI Backend Server (http://localhost:8000)...
start "ClipForge AI Backend" cmd /k "python -m uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 --reload"

echo [2/2] Starting Next.js Frontend App (http://localhost:3000)...
start "ClipForge AI Frontend" cmd /k "cd apps\web && npm run dev"

echo.
echo =======================================================================
echo  🚀 ClipForge AI is launching!
echo.
echo  • Web Interface:  http://localhost:3000
echo  • API Endpoint:   http://localhost:8000/api/health
echo  • API Docs:       http://localhost:8000/docs
echo.
echo  Note: Close the opened command windows to stop the servers.
echo =======================================================================
pause
