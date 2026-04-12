# Signal Bot for Ollama - Run Script

$ErrorActionPreference = "Stop"

Write-Host "===== Signal Bot for Ollama =====" -ForegroundColor Blue
Write-Host ""

# Build
Write-Host "Building..." -ForegroundColor Yellow
docker-compose build --no-cache

# Start Signal API first
Write-Host "Starting Signal API..." -ForegroundColor Yellow
docker-compose up -d signal-api
Start-Sleep -Seconds 5

# Wait for API to be ready
Write-Host "Waiting for Signal API..." -ForegroundColor Yellow
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        $r = Invoke-RestMethod -Uri "http://localhost:18080/v1/about" -TimeoutSec 3 -ErrorAction SilentlyContinue
        if ($r) { $ready = $true; break }
    } catch {}
    Start-Sleep -Seconds 2
}
if (-not $ready) {
    Write-Host "ERROR: Signal API not ready" -ForegroundColor Red
    exit 1
}
Write-Host "Signal API is ready!" -ForegroundColor Green

# Check if account is linked
$needsSetup = $true
try {
    $accounts = Invoke-RestMethod -Uri "http://localhost:18080/v1/accounts" -TimeoutSec 5 -ErrorAction SilentlyContinue
    if ($accounts -and $accounts.Count -gt 0) {
        Write-Host "Account already linked: $($accounts -join ', ')" -ForegroundColor Green
        $needsSetup = $false
    }
} catch {}

# Run setup if needed
if ($needsSetup) {
    Write-Host ""
    Write-Host "No Signal account linked. Running setup..." -ForegroundColor Yellow
    Write-Host ""
    python signal-setup.py
}

# Start the bot
Write-Host ""
Write-Host "Starting bot..." -ForegroundColor Yellow
docker-compose up -d
Write-Host ""
Write-Host "Bot is running!" -ForegroundColor Green
Write-Host "View logs: docker-compose logs -f ollama-signal-bot" -ForegroundColor Cyan
Write-Host ""
docker-compose logs -f ollama-signal-bot