# Stinky OS - diagnose (run in VS Code terminal with venv active)
$ErrorActionPreference = "Continue"
$root = "D:\Work\Project-Genesis"
Set-Location $root
.\.venv\Scripts\activate

Write-Host "=== 1) Ports (Stinky vs Atlas) ===" -ForegroundColor Cyan
netstat -ano | findstr "LISTENING" | findstr "5432 5433 6379 6380 8000 8002 8010 3000"

Write-Host "`n=== 2) Docker ===" -ForegroundColor Cyan
docker compose ps

Write-Host "`n=== 3) Health ===" -ForegroundColor Cyan
Write-Host -NoNewline "API:       "; curl.exe -s -m 3 "http://127.0.0.1:8010/health"
Write-Host ""
Write-Host -NoNewline "Event Log: "; curl.exe -s -m 3 "http://127.0.0.1:8002/health"
Write-Host ""

Write-Host "`n=== 4) Runners API (must show mint) ===" -ForegroundColor Cyan
curl.exe -s -m 10 "http://127.0.0.1:8010/v1/runners?limit=3"

Write-Host "`n`n=== 5) Next.js proxy (what the browser uses) ===" -ForegroundColor Cyan
curl.exe -s -m 10 "http://localhost:3000/api/stinky/v1/runners?limit=2"

Write-Host "`n`n=== 6) Command Center sample ===" -ForegroundColor Cyan
curl.exe -s -m 15 "http://127.0.0.1:8010/v1/command-center" | Select-String '"mint"|migration_tracks|"status"'

Write-Host "`n`n=== 7) Recent log tails ===" -ForegroundColor Cyan
foreach ($n in "api","web","event-log","collector","sentinel") {
    $f = "logs\$n.log"
    if (Test-Path $f) {
        Write-Host "--- $n ---" -ForegroundColor Yellow
        Get-Content $f -Tail 8
    }
}

Write-Host "`n=== DONE ===" -ForegroundColor Green
Write-Host "If section 4 has mints but section 5 fails => restart Next (web)."
Write-Host "If both work but UI empty => hard refresh Ctrl+Shift+R."
