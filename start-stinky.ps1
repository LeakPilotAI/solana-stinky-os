# start-stinky.ps1 - start stack and EXIT (services keep running in background)
# Stop with: powershell -File .\stop-stinky.ps1
$ErrorActionPreference = "Continue"
$root = "D:\Work\Project-Genesis"
Set-Location $root
$venv = "$root\.venv\Scripts\Activate.ps1"
$logDir = "$root\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Start-Svc([string]$Name, [string]$Cmd) {
  $log = Join-Path $logDir "$Name.log"
  try {
    if (Test-Path $log) { Move-Item -Force $log "$log.old" -EA Stop }
  } catch {
    $log = Join-Path $logDir ($Name + "-" + (Get-Date -Format "HHmmss") + ".log")
  }
  try { "" | Set-Content $log -Encoding utf8 -EA Stop } catch {}

  $inner = @"
Set-Location '$root'
if (Test-Path '$venv') { & '$venv' }
`$ErrorActionPreference = 'Continue'
`$env:PYTHONPATH = '$root\services\event-log\src;$root\services\api\src;$root\packages\stinky-core\src;' + `$env:PYTHONPATH
`$env:BROWSER = 'none'
Write-Host '=== $Name ==='
$Cmd 2>&1 | Tee-Object -FilePath '$log' -Append
"@
  $p = Start-Process -FilePath "powershell.exe" -WindowStyle Hidden -PassThru -ArgumentList @(
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $inner
  )
  Write-Host ("  {0,-12} PID {1}" -f $Name, $p.Id) -ForegroundColor Green
  return $p
}

Write-Host ""
Write-Host "  STINKY OS - START" -ForegroundColor Cyan
Write-Host "  $root"
Write-Host ""

Write-Host "[0] Stop previous..." -ForegroundColor Yellow
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$root\stop-stinky.ps1"
Start-Sleep 4

Write-Host "[1] Docker compose up..." -ForegroundColor Yellow
$null = docker info 2>$null
if ($LASTEXITCODE -ne 0) {
  $dd = "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe"
  if (Test-Path $dd) { Start-Process $dd; Start-Sleep 20 }
}
docker compose -f "$root\docker-compose.yml" up -d
Start-Sleep 5

Write-Host "[1b] Redis PING..." -ForegroundColor Yellow
$ok = $false
for ($i = 0; $i -lt 30; $i++) {
  try {
    $r = docker exec stinky-redis redis-cli ping 2>$null
    if ("$r" -match "PONG") { $ok = $true; break }
  } catch {}
  Start-Sleep 2
}
if ($ok) { Write-Host "  Redis PONG" -ForegroundColor Green }
else { Write-Host "  Redis not ready - continuing anyway" -ForegroundColor Yellow }

Write-Host "[2] Starting services..." -ForegroundColor Yellow
$procs = @{}
$procs["event-log"] = Start-Svc "event-log" "uvicorn event_log.api:app --port 8002 --host 127.0.0.1"
Start-Sleep 5
$procs["api"]       = Start-Svc "api" "stinky-api"
Start-Sleep 4
$procs["sentinel"]  = Start-Svc "sentinel" "stinky-sentinel"
Start-Sleep 2
$procs["discord"]   = Start-Svc "discord" "stinky-discord"
Start-Sleep 1
$procs["collector"] = Start-Svc "collector" "stinky-collector"
Start-Sleep 1
$procs["entities"]  = Start-Svc "entities" "stinky-entities"
Start-Sleep 1
$procs["web"]       = Start-Svc "web" "Set-Location apps\web; npm run dev -- -p 3000 -H 127.0.0.1"
Start-Sleep 1
$procs["maintain"]  = Start-Svc "maintain" "while (`$true) { try { stinky-collector learn-success } catch {}; try { stinky-collector recompute-performance } catch {}; Start-Sleep -Seconds 21600 }"

$procs.GetEnumerator() | ForEach-Object {
  if ($_.Value -and $_.Value.Id) { "$($_.Key)=$($_.Value.Id)" }
} | Set-Content "logs\stinky-pids.txt" -Encoding ascii

Write-Host "[3] Health..." -ForegroundColor Yellow
Start-Sleep 6
foreach ($url in @("http://127.0.0.1:8002/health", "http://127.0.0.1:8010/health")) {
  try {
    $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5
    Write-Host "  $url -> $($r.Content)" -ForegroundColor Green
  } catch {
    Write-Host "  $url -> not ready yet (check logs later)" -ForegroundColor Yellow
  }
}

Write-Host "[4] Open Command Center..." -ForegroundColor Yellow
try { Start-Process "http://127.0.0.1:3000/command-center" } catch {}

Write-Host ""
Write-Host "  READY - services running in background." -ForegroundColor Green
Write-Host "  UI: http://127.0.0.1:3000/command-center" -ForegroundColor Cyan
Write-Host "  STOP when done:" -ForegroundColor Yellow
Write-Host "    powershell -NoProfile -ExecutionPolicy Bypass -File .\stop-stinky.ps1"
Write-Host ""
# IMPORTANT: no finally-stop. This script exits; services stay up until you run stop.
