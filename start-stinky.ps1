# start-stinky.ps1 - one-click Genesis operator box.
# Desktop shortcut: Start-Stinky-OS.cmd
# Preserves .env. Gate 1 stays 150k / 200k clamp.
# Stop with Stop-Stinky-OS.cmd / stop-stinky.ps1
param(
  [switch]$SkipSync,
  [switch]$SkipInstall
)
$ErrorActionPreference = "Continue"
$root = "D:\Work\Project-Genesis"
$repo = "https://github.com/LeakPilotAI/solana-stinky-os.git"
$logDir = Join-Path $root "logs"
$venvPy = Join-Path $root ".venv\Scripts\python.exe"
$pidFile = Join-Path $logDir "stinky-pids.txt"

if (-not (Test-Path -LiteralPath $root)) {
  Write-Host "Project folder missing. Cloning $repo" -ForegroundColor Yellow
  New-Item -ItemType Directory -Force -Path (Split-Path $root) | Out-Null
  git clone --depth 1 $repo $root
}
Set-Location $root
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Write-Step([string]$Msg) { Write-Host ""; Write-Host $Msg -ForegroundColor Cyan }
function Write-Ok([string]$Msg) { Write-Host "  $Msg" -ForegroundColor Green }
function Write-Warn([string]$Msg) { Write-Host "  $Msg" -ForegroundColor Yellow }

function Backup-DotEnv {
  $envFile = Join-Path $root ".env"
  $bak = Join-Path $logDir "env.backup"
  if (Test-Path -LiteralPath $envFile) {
    Copy-Item -Force -LiteralPath $envFile -Destination $bak
    return $bak
  }
  return $null
}

function Restore-DotEnv([string]$Bak) {
  if ($Bak -and (Test-Path -LiteralPath $Bak)) {
    Copy-Item -Force -LiteralPath $Bak -Destination (Join-Path $root ".env")
  }
}

function Sync-FromGitHub {
  if ($SkipSync) { Write-Warn "SkipSync - using files on disk"; return }
  if ($env:STINKY_SKIP_SYNC -eq "1") { Write-Warn "STINKY_SKIP_SYNC=1"; return }
  $bak = Backup-DotEnv
  try {
    if (Test-Path (Join-Path $root ".git")) {
      Write-Step "[sync] git fetch + reset origin/main (keeps .env)"
      git -C $root remote set-url origin $repo 2>$null
      git -C $root fetch origin 2>&1 | Out-Host
      git -C $root reset --hard origin/main 2>&1 | Out-Host
      git -C $root checkout -f -B main origin/main 2>&1 | Out-Host
      Write-Ok ("tree = " + (git -C $root rev-parse --short HEAD))
    } else {
      Write-Step "[sync] overlay from GitHub zip (folder is not a git clone)"
      $zip = Join-Path $env:TEMP "genesis-main.zip"
      $extract = Join-Path $env:TEMP "genesis-main-src"
      if (Test-Path $extract) { Remove-Item -Recurse -Force $extract }
      Invoke-WebRequest -Uri "https://github.com/LeakPilotAI/solana-stinky-os/archive/refs/heads/main.zip" -OutFile $zip -UseBasicParsing
      Expand-Archive -Force -Path $zip -DestinationPath $extract
      $src = Get-ChildItem $extract -Directory | Select-Object -First 1
      & robocopy $src.FullName $root /E /XD .git .venv node_modules logs dumps .next __pycache__ /XF .env /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
      Write-Ok "overlay complete"
    }
  } catch {
    Write-Warn ("sync failed: " + $_.Exception.Message + " - starting with files on disk")
  }
  Restore-DotEnv $bak
}

function Ensure-DotEnv {
  $envFile = Join-Path $root ".env"
  $example = Join-Path $root ".env.example"
  if (-not (Test-Path -LiteralPath $envFile)) {
    if (Test-Path -LiteralPath $example) {
      Copy-Item $example $envFile
      Write-Warn "created .env from .env.example - add Discord token locally if you want alerts"
    }
  } else {
    Write-Ok ".env present (secrets kept)"
  }
}

function Get-Python {
  $candidates = @(
    @{ Exe = "py"; Args = @("-3.12") },
    @{ Exe = "py"; Args = @("-3") },
    @{ Exe = "python"; Args = @() }
  )
  foreach ($c in $candidates) {
    try {
      $ver = & $c.Exe @($c.Args + "--version") 2>&1 | Out-String
      if ($ver -match "Python 3\.(1[2-9]|[2-9]\d)") {
        return $c
      }
    } catch {}
  }
  throw "Python 3.12+ not found. Install python.org 3.12 and retry."
}

function Ensure-Venv {
  if ($SkipInstall -and (Test-Path $venvPy)) { return }
  Write-Step "[deps] Python venv + editable installs"
  $py = Get-Python
  if (-not (Test-Path $venvPy)) {
    & $py.Exe @($py.Args + @("-m", "venv", (Join-Path $root ".venv")))
  }
  & $venvPy -m pip install -U pip wheel hatchling 2>&1 | Select-Object -Last 3 | Out-Host
  $pkgs = @(
    ".\packages\stinky-core",
    ".\services\event-log",
    ".\services\api",
    ".\services\sentinel",
    ".\services\discord-bot",
    ".\services\post-migration-collector",
    ".\services\entity-resolver"
  )
  foreach ($p in $pkgs) {
    Write-Host "  pip install -e $p"
    & $venvPy -m pip install -e $p 2>&1 | Select-Object -Last 2 | Out-Host
  }
  Write-Ok "python packages installed"
}

function Ensure-Web {
  $web = Join-Path $root "apps\web"
  if (-not (Test-Path (Join-Path $web "package.json"))) { return }
  Write-Step "[deps] npm install (web)"
  Push-Location $web
  try {
    npm install --no-fund --no-audit 2>&1 | Select-Object -Last 5 | Out-Host
  } finally { Pop-Location }
  Write-Ok "web deps ready"
}

function Ensure-Docker {
  Write-Step "[docker] compose up (Postgres 5433 / Redis 6380 / MinIO 9010)"
  $null = docker info 2>$null
  if ($LASTEXITCODE -ne 0) {
    $dd = "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe"
    if (Test-Path $dd) {
      Write-Warn "starting Docker Desktop..."
      Start-Process $dd
    }
    for ($i = 0; $i -lt 40; $i++) {
      Start-Sleep 3
      $null = docker info 2>$null
      if ($LASTEXITCODE -eq 0) { break }
    }
  }
  $null = docker info 2>$null
  if ($LASTEXITCODE -ne 0) { throw "Docker is not running. Start Docker Desktop and double-click Genesis again." }
  docker compose -f "$root\docker-compose.yml" up -d 2>&1 | Out-Host
  for ($i = 0; $i -lt 40; $i++) {
    $pg = docker exec stinky-postgres pg_isready -U stinky -d stinky 2>$null
    $rd = docker exec stinky-redis redis-cli ping 2>$null
    if (("$pg" -match "accepting") -and ("$rd" -match "PONG")) {
      Write-Ok "Postgres + Redis ready"
      return
    }
    Start-Sleep 2
  }
  Write-Warn "Postgres/Redis not confirmed ready - continuing"
}

function Apply-Schema {
  Write-Step "[schema] apply SQL migrations (fail-soft)"
  $files = Get-ChildItem -Path (Join-Path $root "services") -Recurse -Filter "*.sql" |
    Where-Object { $_.FullName -match "migrations" } |
    Sort-Object Name
  foreach ($f in $files) {
    Write-Host ("  " + $f.Name)
    Get-Content -LiteralPath $f.FullName -Raw | docker exec -i stinky-postgres psql -U stinky -d stinky -v ON_ERROR_STOP=0 2>&1 | Out-Null
  }
  Write-Ok "schema applied"
}

function Start-Svc([string]$Name, [string]$Cmd) {
  $log = Join-Path $logDir "$Name.log"
  try { if (Test-Path $log) { Move-Item -Force $log "$log.old" } } catch {}
  try { "" | Set-Content $log -Encoding utf8 } catch {}
  $pyPath = @(
    "$root\packages\stinky-core\src",
    "$root\services\event-log\src",
    "$root\services\api\src",
    "$root\services\sentinel\src",
    "$root\services\discord-bot\src",
    "$root\services\post-migration-collector\src",
    "$root\services\entity-resolver\src"
  ) -join ";"
  $inner = @"
Set-Location '$root'
`$ErrorActionPreference = 'Continue'
if (Test-Path '$root\.venv\Scripts\Activate.ps1') { & '$root\.venv\Scripts\Activate.ps1' }
`$env:PYTHONPATH = '$pyPath;' + `$env:PYTHONPATH
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

function Wait-Http([string]$Url, [int]$Seconds = 60) {
  $deadline = (Get-Date).AddSeconds($Seconds)
  while ((Get-Date) -lt $deadline) {
    try {
      $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
      if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500) { return $true }
    } catch {}
    Start-Sleep 2
  }
  return $false
}

Write-Host ""
Write-Host "  GENESIS  intel-v1.11.0-operator" -ForegroundColor Cyan
Write-Host "  $root"
Write-Host "  Gate 1 = 150k USD / 5m  clamp 200k  (not a buy)" -ForegroundColor DarkGray
Write-Host ""

Write-Step "[0] Stop previous instance"
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "stop-stinky.ps1")
Start-Sleep 3

Sync-FromGitHub
Ensure-DotEnv
Ensure-Venv
Ensure-Web
Ensure-Docker
Apply-Schema

Write-Step "[services] start"
$procs = [ordered]@{}
$procs["event-log"] = Start-Svc "event-log" "uvicorn event_log.api:app --port 8002 --host 127.0.0.1"
Start-Sleep 4
$procs["api"]       = Start-Svc "api" "stinky-api"
Start-Sleep 3
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
} | Set-Content $pidFile -Encoding ascii

Write-Step "[health]"
$apiOk = Wait-Http "http://127.0.0.1:8010/health" 75
$elOk  = Wait-Http "http://127.0.0.1:8002/health" 20
if ($apiOk) { Write-Ok "API http://127.0.0.1:8010/health" } else { Write-Warn "API not ready - see logs\api.log" }
if ($elOk)  { Write-Ok "event-log http://127.0.0.1:8002/health" } else { Write-Warn "event-log not ready - see logs\event-log.log" }

$webUp = $false
for ($i = 0; $i -lt 45; $i++) {
  if (Get-NetTCPConnection -LocalPort 3000 -State Listen -EA SilentlyContinue) { $webUp = $true; break }
  Start-Sleep 1
}
if ($webUp) { Write-Ok "web :3000" } else { Write-Warn "web not listening yet - see logs\web.log" }

Write-Step "[ui] open operator desk (one tab)"
Start-Process "http://127.0.0.1:3000/operator"

try {
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "install-desktop-shortcut.ps1") | Out-Null
} catch {}

Write-Host ""
Write-Host "  READY. Services stay up after this window closes." -ForegroundColor Green
Write-Host "  Operator:  http://127.0.0.1:3000/operator" -ForegroundColor Cyan
Write-Host "  Command:   http://127.0.0.1:3000/command-center" -ForegroundColor Cyan
Write-Host "  Stop:      double-click  Stop Genesis  on the desktop" -ForegroundColor Yellow
Write-Host "  LIVE GATE-1 is NOT OBSERVED until a real 150k USD / 5m print." -ForegroundColor DarkGray
Write-Host ""
Start-Sleep 6
