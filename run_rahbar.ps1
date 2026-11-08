# ==============================================================================
# RAHBAR — Live Full-Stack Launcher (UI + API + Chroma + Redis + Ollama)
# ==============================================================================

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "   Starting RAHBAR Local Environment for Live Demo        " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Start WSL Background Daemons (Redis + Ollama)
Write-Host "`n[1/3] Ensuring Redis & Ollama are active in WSL..." -ForegroundColor Yellow
wsl -d Ubuntu-24.04 -u root -e bash -c "service redis-server start; systemctl start ollama 2>/dev/null || true"

# 2. Start ChromaDB Server (Port 8000)
$chromaCheck = Test-NetConnection -ComputerName localhost -Port 8000 -InformationLevel Quiet
if (-not $chromaCheck) {
    Write-Host "[2/3] Launching ChromaDB Vector Store on port 8000..." -ForegroundColor Yellow
    Start-Process -NoNewWindow -FilePath "powershell.exe" -ArgumentList "-Command", "chroma run --path ./chroma_db --port 8000"
    Start-Sleep -Seconds 3
} else {
    Write-Host "[2/3] ChromaDB is already listening on port 8000." -ForegroundColor Green
}

# 3. Configure Environment Variables for FastAPI
$env:RETRIEVER = "chroma"
$env:LLM_PROVIDER = "ollama-host"
$env:CHROMA_HOST = "localhost"
$env:CHROMA_PORT = "8000"
$env:CHROMA_COLLECTION = "rahbar"
$env:EMBED_MODEL = "nomic-embed-text"
$env:LLM_MODEL = "llama3.2:1b"
$env:OLLAMA_URL = "http://127.0.0.1:11434"
$env:REDIS_URL = "redis://localhost:6379"
$env:LLM_TIMEOUT = "60"
$env:SERVE_UI_DIR = (Resolve-Path "ui").Path

# 4. Open Default Web Browser directly to the UI
Write-Host "[3/3] Opening Web Interface at http://localhost:8080/ ..." -ForegroundColor Yellow
Start-Process "http://localhost:8080/"

# 5. Start API & Web Server
Write-Host "`n==========================================================" -ForegroundColor Green
Write-Host "   RAHBAR is LIVE at http://localhost:8080/              " -ForegroundColor Green
Write-Host "   Press Ctrl+C to stop the server when done.            " -ForegroundColor Green
Write-Host "==========================================================`n" -ForegroundColor Green

Set-Location "api"
uvicorn app.main:app --host 0.0.0.0 --port 8080
