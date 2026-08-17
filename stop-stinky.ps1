# stop-stinky.ps1 - kill Stinky apps + stop Genesis containers
$ErrorActionPreference = "Continue"
$root = "D:\Work\Project-Genesis"
Set-Location $root
Write-Host "STOPPING Stinky OS..." -ForegroundColor Yellow

function Kill-Pid([int]$Id) {
  if ($Id -le 0) { return }
  try {
    $p = Get-CimInstance Win32_Process -Filter "ProcessId=$Id" -EA SilentlyContinue
    if ($p -and $p.Name -match "docker|Docker Desktop|com\.docker") { return }
  } catch {}
  taskkill /PID $Id /T /F 2>$null | Out-Null
}

$pidFile = "logs\stinky-pids.txt"
if (Test-Path $pidFile) {
  Get-Content $pidFile | ForEach-Object {
    if ($_ -match "=(\d+)\s*$") { Kill-Pid ([int]$Matches[1]) }
    elseif ($_ -match "^\d+$") { Kill-Pid ([int]$_) }
  }
  Remove-Item $pidFile -Force -EA SilentlyContinue
}

Get-Process -Name "stinky*" -EA SilentlyContinue | ForEach-Object { Kill-Pid $_.Id }

Get-CimInstance Win32_Process -EA SilentlyContinue | ForEach-Object {
  $c = $_.CommandLine
  if (-not $c) { return }
  if ($c -match "docker|Docker Desktop") { return }
  if ($c -match "atlas" -and $c -notmatch "Project-Genesis") { return }
  if ($c -match "8000" -and $c -match "app\.main:app") { return }
  if ($c -match "Project-Genesis" -and $c -match "uvicorn|stinky-|next dev|npm run|event_log|stinky_api") {
    Kill-Pid ([int]$_.ProcessId)
  }
}

foreach ($port in 8002, 8010, 3000, 8001) {
  Get-NetTCPConnection -LocalPort $port -EA SilentlyContinue | ForEach-Object {
    Kill-Pid ([int]$_.OwningProcess)
  }
}

Start-Sleep 2
Get-ChildItem logs -Filter "*.log" -EA SilentlyContinue | ForEach-Object {
  try { Move-Item -Force $_.FullName ($_.FullName + ".old") -EA Stop } catch {}
}

Write-Host "Stopping Genesis containers..." -ForegroundColor Yellow
docker compose -f "$root\docker-compose.yml" stop 2>$null
Write-Host "STOPPED." -ForegroundColor Green
