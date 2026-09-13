# ClipForge AI — PowerShell One-Click Launcher

Write-Host "=======================================================================" -ForegroundColor Cyan
Write-Host "                🎬 ClipForge AI — One-Click Launcher" -ForegroundColor Cyan
Write-Host "=======================================================================" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path ".env")) {
    Write-Host "[.env] Creating environment file from .env.example..." -ForegroundColor Yellow
    Copy-Item .env.example .env
}

Write-Host "[1/2] Starting FastAPI Backend Server (http://localhost:8000)..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "python -m uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 --reload"

Write-Host "[2/2] Starting Next.js Frontend App (http://localhost:3000)..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd apps/web; npm run dev"

Write-Host ""
Write-Host "=======================================================================" -ForegroundColor Cyan
Write-Host "  🚀 ClipForge AI is launching!" -ForegroundColor Green
Write-Host ""
Write-Host "  • Web Interface:  http://localhost:3000" -ForegroundColor White
Write-Host "  • API Endpoint:   http://localhost:8000/api/health" -ForegroundColor White
Write-Host "  • API Docs:       http://localhost:8000/docs" -ForegroundColor White
Write-Host ""
Write-Host "  Note: Close the opened PowerShell windows to stop the servers." -ForegroundColor Gray
Write-Host "=======================================================================" -ForegroundColor Cyan
