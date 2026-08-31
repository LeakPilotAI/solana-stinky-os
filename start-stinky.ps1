# start-stinky.ps1 - one-click Genesis operator box.
# Desktop shortcut target is Start-Stinky-OS.cmd (cmd.exe /d /k, absolute paths).
# Services are started in a new console so closing this window does NOT kill them.
# Double-click while healthy => ALREADY RUNNING (no duplicate processes).
# Gate 1 stays 150k / 200k clamp. This script does not change intelligence.
# Stop with Stop-Stinky-OS.cmd / stop-stinky.ps1
param(
  [switch]$SkipSync,
  [switch]$Sync,
  [switch]$Restart,
  [switch]$SkipInstall
)

$ErrorActionPreference = "Continue"
$PSDefaultParameterValues["*:ErrorAction"] = "Continue"

function Get-ScriptRoot {
  if ($PSScriptRoot) { return $PSScriptRoot }
  if ($MyInvocation.MyCommand.Path) { return (Split-Path -Parent $MyInvocation.MyCommand.Path) }
  return (Get-Location).Path
}

$here = Get-ScriptRoot
$operatorRoot = "D:\Work\Project-Genesis"
if (Test-Path -LiteralPath (Join-Path $here "docker-compose.yml")) {
  $root = $here
} elseif (Test-Path -LiteralPath (Join-Path $operatorRoot "docker-compose.yml")) {
  $root = $operatorRoot
} else {
  $root = $here
}

$repo = "https://github.com/LeakPilotAI/solana-stinky-os.git"
$logDir = Join-Path $root "logs"
$venvPy = Join-Path $root ".venv\Scripts\python.exe"
$pidFile = Join-Path $logDir "stinky-pids.txt"
$startupLog = Join-Path $logDir "startup.log"
$launchDir = Join-Path $logDir "launchers"
$psExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
if (-not (Test-Path -LiteralPath $psExe)) { $psExe = "powershell.exe" }
$cmdExe = Join-Path $env:SystemRoot "System32\cmd.exe"
$failed = $false
$script:health = [ordered]@{}

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
New-Item -ItemType Directory -Force -Path $launchDir | Out-Null
Set-Location -LiteralPath $root

function Write-Step([string]$Msg) { Write-Host ""; Write-Host $Msg -ForegroundColor Cyan }
function Write-Ok([string]$Msg) { Write-Host "  $Msg" -ForegroundColor Green }
function Write-Warn([string]$Msg) { Write-Host "  $Msg" -ForegroundColor Yellow }
function Write-Err([string]$Msg) { Write-Host "  $Msg" -ForegroundColor Red }

function Redact-Line([string]$Line) {
  if ($Line -match "(?i)(API_KEY|TOKEN|SECRET|PASSWORD|PRIVATE_KEY|DISCORD_TOKEN)\s*=") {
    return ($Line -replace "(?i)((?:API_KEY|TOKEN|SECRET|PASSWORD|PRIVATE_KEY|DISCORD_TOKEN)\s*=\s*).+", '$1***')
  }
  return $Line
}

function Write-StartupLog {
  param([string]$Component, [string]$Result, [string]$Command = "", [string]$PidValue = "", [string]$Reason = "")
  $ts = Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"
  $parts = @($ts, $Component, $Result)
  if ($PidValue) { $parts += "pid=$PidValue" }
  if ($Command) { $parts += "cmd=$(Redact-Line $Command)" }
  if ($Reason) { $parts += "reason=$(Redact-Line $Reason)" }
  $line = $parts -join "  "
  Add-Content -LiteralPath $startupLog -Value $line -Encoding ascii
}

function Fail-Component {
  param([string]$Name, [string]$Status, [string]$Reason, [string]$LogFile = "", [string]$Next = "")
  $script:failed = $true
  $script:health[$Name] = $Status
  Write-Host ""
  Write-Host "GENESIS STARTUP FAILED" -ForegroundColor Red
  Write-Host "Component: $Name"
  Write-Host "Status:    $Status"
  Write-Host "Reason:    $Reason"
  if ($LogFile) { Write-Host "Log:       $LogFile" }
  if ($Next) { Write-Host "Next:      $Next" }
  Write-StartupLog -Component $Name -Result $Status -Reason $Reason
}

function Get-ListenPid([int]$Port) {
  try {
    $c = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
      Select-Object -First 1
    if ($c -and $c.OwningProcess) { return [int]$c.OwningProcess }
  } catch {}
  try {
    $needle = ":" + $Port + " "
    foreach ($ln in (netstat -ano 2>$null | Select-String "LISTENING")) {
      if ($ln.Line -like "*$needle*" -or $ln.Line -match ":$Port\s+") {
        if ($ln.Line -match "LISTENING\s+(\d+)\s*$") { return [int]$Matches[1] }
      }
    }
  } catch {}
  return 0
}

function Get-ProcessCommand([int]$Id) {
  if ($Id -le 0) { return "" }
  try {
    $p = Get-CimInstance Win32_Process -Filter "ProcessId=$Id" -ErrorAction SilentlyContinue
    if ($p) { return [string]$p.CommandLine }
  } catch {}
  return ""
}

function Test-GenesisOwned([int]$Id) {
  if ($Id -le 0) { return $false }
  try {
    $p = Get-CimInstance Win32_Process -Filter "ProcessId=$Id" -ErrorAction SilentlyContinue
    if (-not $p) { return $false }
    $n = [string]$p.Name
    if ($n -match "(?i)docker|com\.docker") { return $false }
    $c = [string]$p.CommandLine
    if (-not $c) { return $false }
    $rootEsc = [regex]::Escape($root)
    if ($c -match $rootEsc) { return $true }
    if ($c -match "Project-Genesis") { return $true }
    if ($c -match "solana-stinky-os") { return $true }
    if ($c -match "run-(event-log|api|sentinel|discord|collector|entities|web|maintain)\.ps1") { return $true }
    return $false
  } catch { return $false }
}

function Test-HttpOk([string]$Url, [int]$TimeoutSec = 4) {
  try {
    $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec
    return ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500)
  } catch { return $false }
}

function Wait-Http([string]$Url, [int]$Seconds = 60) {
  $deadline = (Get-Date).AddSeconds($Seconds)
  while ((Get-Date) -lt $deadline) {
    if (Test-HttpOk $Url 3) { return $true }
    Start-Sleep 2
  }
  return $false
}

function Get-JsonUrl([string]$Url) {
  try {
    return Invoke-RestMethod -Uri $Url -TimeoutSec 8
  } catch { return $null }
}

function Test-CoreHealthy {
  $api = Test-HttpOk "http://127.0.0.1:8010/health" 4
  $web = Test-HttpOk "http://127.0.0.1:3000/operator" 4
  return ($api -and $web)
}

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
  if (-not $Sync) { return }
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
      Write-StartupLog -Component "sync" -Result "ok" -Command "git reset --hard origin/main"
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
      Write-StartupLog -Component "sync" -Result "ok" -Command "robocopy overlay"
    }
  } catch {
    Write-Warn ("sync failed: " + $_.Exception.Message + " - starting with files on disk")
    Write-StartupLog -Component "sync" -Result "failed" -Reason $_.Exception.Message
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
    Write-Ok ".env present (secrets kept, not logged)"
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
      if ($ver -match "Python 3\.(1[2-9]|[2-9]\d)") { return $c }
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
  Write-StartupLog -Component "venv" -Result "ok" -Command "pip install -e packages/services"
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
  Write-StartupLog -Component "web-deps" -Result "ok" -Command "npm install"
}

function Ensure-Docker {
  Write-Step "[docker] compose up (Postgres 5433 / Redis 6380 / MinIO 9010)"
  $null = docker info 2>$null
  if ($LASTEXITCODE -ne 0) {
    $dd = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
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
  if ($LASTEXITCODE -ne 0) {
    Fail-Component "Docker" "DOWN" "Docker is not running" "" "Start Docker Desktop and double-click Genesis again."
    throw "Docker is not running."
  }
  docker compose -f "$root\docker-compose.yml" up -d 2>&1 | Out-Host
  Write-StartupLog -Component "docker" -Result "started" -Command "docker compose up -d"
  $pgOk = $false
  $rdOk = $false
  for ($i = 0; $i -lt 40; $i++) {
    $pg = docker exec stinky-postgres pg_isready -U stinky -d stinky 2>$null
    $rd = docker exec stinky-redis redis-cli ping 2>$null
    if ("$pg" -match "accepting") { $pgOk = $true }
    if ("$rd" -match "PONG") { $rdOk = $true }
    if ($pgOk -and $rdOk) { break }
    Start-Sleep 2
  }
  if ($pgOk) { $script:health["DATABASE"] = "CONNECTED"; Write-Ok "Postgres ready (host 5433)" }
  else {
    $script:health["DATABASE"] = "DOWN"
    Fail-Component "DATABASE" "DOWN" "pg_isready did not report accepting connections" "" "Wait for Docker, then double-click Genesis again."
  }
  if ($rdOk) { $script:health["REDIS"] = "CONNECTED"; Write-Ok "Redis PONG (host 6380)" }
  else {
    $script:health["REDIS"] = "DOWN"
    Fail-Component "REDIS" "DOWN" "redis-cli ping did not return PONG" "" "Wait for Docker, then double-click Genesis again."
  }
  Write-StartupLog -Component "postgres" -Result $script:health["DATABASE"] -Command "pg_isready -U stinky -d stinky"
  Write-StartupLog -Component "redis" -Result $script:health["REDIS"] -Command "redis-cli ping"
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
  Write-StartupLog -Component "schema" -Result "ok"
}

function Invoke-PersistenceSmoke {
  Write-Step "[persist] harmless smoke row (genesis_launcher_smoke)"
  $sql = @"
CREATE TABLE IF NOT EXISTS genesis_launcher_smoke (
  k text primary key,
  v text,
  at timestamptz default now()
);
INSERT INTO genesis_launcher_smoke(k, v) VALUES ('launcher', 'ok')
  ON CONFLICT (k) DO UPDATE SET v = 'ok', at = now();
SELECT v FROM genesis_launcher_smoke WHERE k = 'launcher';
"@
  $raw = $sql | docker exec -i stinky-postgres psql -U stinky -d stinky -v ON_ERROR_STOP=0 -t -A 2>&1
  if ("$raw" -match "ok") {
    Write-Ok "wrote and read launcher smoke row"
    Write-StartupLog -Component "persist" -Result "ok" -Reason "write+read genesis_launcher_smoke"
  } else {
    Write-Warn "persistence smoke did not confirm (not fatal)"
    Write-StartupLog -Component "persist" -Result "UNKNOWN" -Reason "smoke row not confirmed"
  }
}

function Find-WrapperPid([string]$Name) {
  $marker = "run-$Name.ps1"
  try {
    $hits = Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
      Where-Object { $_.CommandLine -and ($_.CommandLine -like "*$marker*") }
    foreach ($h in $hits) { return [int]$h.ProcessId }
  } catch {}
  return 0
}

function Test-PidAlive([int]$Id) {
  if ($Id -le 0) { return $false }
  try {
    $p = Get-Process -Id $Id -ErrorAction SilentlyContinue
    return [bool]$p
  } catch { return $false }
}

function Start-DetachedSvc {
  param([string]$Name, [string]$Cmd, [int]$Port = 0, [switch]$Required)
  if ($Port -gt 0) {
    $owner = Get-ListenPid $Port
    if ($owner -gt 0) {
      if (Test-GenesisOwned $owner) {
        Write-Ok ("{0,-12} ALREADY RUNNING  pid {1}  port {2}" -f $Name, $owner, $Port)
        Write-StartupLog -Component $Name -Result "ALREADY RUNNING" -PidValue "$owner"
        $script:health[$Name] = "ALREADY RUNNING"
        return $owner
      }
      $reason = "port $Port in use by pid $owner (not Genesis-owned). Not killed (ATLAS isolation)."
      if ($Required) {
        Fail-Component $Name "DOWN" $reason (Join-Path $logDir "$Name.log") "Free the port or stop the other stack, then retry."
      } else {
        Write-Warn ("{0,-12} skipped: {1}" -f $Name, $reason)
        Write-StartupLog -Component $Name -Result "skipped" -Reason $reason
      }
      return 0
    }
  }

  $existing = Find-WrapperPid $Name
  if ($existing -gt 0 -and (Test-PidAlive $existing)) {
    Write-Ok ("{0,-12} ALREADY RUNNING  pid {1}" -f $Name, $existing)
    Write-StartupLog -Component $Name -Result "ALREADY RUNNING" -PidValue "$existing"
    $script:health[$Name] = "ALREADY RUNNING"
    return $existing
  }

  $log = Join-Path $logDir "$Name.log"
  try { if (Test-Path $log) { Move-Item -Force $log "$log.old" } } catch {}
  try { "" | Set-Content $log -Encoding ascii } catch {}
  $pyPath = @(
    (Join-Path $root "packages\stinky-core\src"),
    (Join-Path $root "services\event-log\src"),
    (Join-Path $root "services\api\src"),
    (Join-Path $root "services\sentinel\src"),
    (Join-Path $root "services\discord-bot\src"),
    (Join-Path $root "services\post-migration-collector\src"),
    (Join-Path $root "services\entity-resolver\src")
  ) -join ";"
  $wrapper = Join-Path $launchDir "run-$Name.ps1"
  $activate = Join-Path $root ".venv\Scripts\Activate.ps1"
  $body = @"
`$ErrorActionPreference = 'Continue'
Set-Location -LiteralPath '$root'
if (Test-Path -LiteralPath '$activate') { & '$activate' }
`$env:PYTHONPATH = '$pyPath;' + `$env:PYTHONPATH
`$env:BROWSER = 'none'
`$env:STINKY_ROOT = '$root'
Write-Host ('=== $Name pid=' + `$PID)
Add-Content -LiteralPath '$log' -Value ('[' + (Get-Date -Format o) + '] start pid=' + `$PID)
$Cmd 2>&1 | Tee-Object -FilePath '$log' -Append
Add-Content -LiteralPath '$log' -Value ('[' + (Get-Date -Format o) + '] exit LASTEXITCODE=' + `$LASTEXITCODE)
"@
  Set-Content -LiteralPath $wrapper -Value $body -Encoding ascii
  try { Unblock-File -LiteralPath $wrapper -ErrorAction SilentlyContinue } catch {}

  # cmd START creates a new console + process group and breaks away from the
  # Explorer job object. Closing the launcher window must not kill services.
  # Concatenate the start line so Windows PowerShell 5.1 does not eat nested quotes.
  $title = "genesis-$Name"
  $cmdLine = 'start "' + $title + '" /MIN "' + $psExe + '" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "' + $wrapper + '"'
  & $cmdExe /d /c $cmdLine
  Start-Sleep -Milliseconds 800
  $id = Find-WrapperPid $Name
  if ($id -le 0) {
    Start-Sleep 1
    $id = Find-WrapperPid $Name
  }
  if ($id -gt 0) {
    Write-Ok ("{0,-12} PID {1}" -f $Name, $id)
    Write-StartupLog -Component $Name -Result "started" -PidValue "$id" -Command $Cmd
    $script:health[$Name] = "STARTED"
    return $id
  }
  $reason = "process did not appear after start"
  if ($Required) {
    Fail-Component $Name "DOWN" $reason $log "Open the log and retry. Do not start a second copy."
  } else {
    Write-Warn ("{0,-12} $reason" -f $Name)
    Write-StartupLog -Component $Name -Result "DOWN" -Reason $reason
    $script:health[$Name] = "DOWN"
  }
  return 0
}

function Write-PidFile($map) {
  $lines = @()
  foreach ($k in $map.Keys) {
    if ($map[$k] -and [int]$map[$k] -gt 0) { $lines += "$k=$($map[$k])" }
  }
  Set-Content -LiteralPath $pidFile -Value $lines -Encoding ascii
}

function Show-HealthTable {
  Write-Host ""
  Write-Host ("  {0,-22} {1}" -f "COMPONENT", "STATUS") -ForegroundColor Cyan
  Write-Host ("  {0,-22} {1}" -f "---------", "------")
  foreach ($k in $script:health.Keys) {
    $v = $script:health[$k]
    $color = "Gray"
    if ($v -match "UP|CONNECTED|READY|RUNNING|ALREADY|OBSERVED|LIVE") { $color = "Green" }
    elseif ($v -match "DOWN|FAILED") { $color = "Red" }
    elseif ($v -match "DEGRADED|WARN") { $color = "Yellow" }
    Write-Host ("  {0,-22} {1}" -f $k, $v) -ForegroundColor $color
  }
}

Write-Host ""
Write-Host "  GENESIS  intel-v1.11.0-operator" -ForegroundColor Cyan
Write-Host "  $root"
Write-Host ("  PowerShell " + $PSVersionTable.PSVersion.ToString() + "  cwd=" + (Get-Location).Path) -ForegroundColor DarkGray
Write-Host "  Gate 1 = 150k USD / 5m  clamp 200k  (not a buy)" -ForegroundColor DarkGray
Write-Host "  Closing this window does NOT stop Genesis." -ForegroundColor DarkGray
Write-Host ""
Write-StartupLog -Component "launcher" -Result "begin" -Command "start-stinky.ps1" -Reason ("ps=" + $PSVersionTable.PSVersion.ToString() + " root=" + $root)

if (-not $Restart -and (Test-CoreHealthy)) {
  Write-Step "[duplicate] core already healthy"
  Write-Ok "ALREADY RUNNING - not starting another copy"
  $script:health["BACKEND"] = "UP"
  $script:health["FRONTEND"] = "UP"
  $script:health["OPERATOR"] = "READY"
  $op = Get-JsonUrl "http://127.0.0.1:8010/v1/operator"
  if ($op -and $op.system_status) { $script:health["SYSTEM"] = [string]$op.system_status } else { $script:health["SYSTEM"] = "UNKNOWN" }
  if ($op -and $op.database -and $op.database.status) { $script:health["DATABASE"] = [string]$op.database.status } else { $script:health["DATABASE"] = "UNKNOWN" }
  if ($op -and $op.database -and $null -ne $op.database.active_watch_count) {
    $script:health["ACTIVE WATCHES"] = [string]$op.database.active_watch_count
  } else {
    $script:health["ACTIVE WATCHES"] = "UNKNOWN"
  }
  if ($op -and $op.live_data_status) { $script:health["LIVE MARKET DATA"] = [string]$op.live_data_status } else { $script:health["LIVE MARKET DATA"] = "UNKNOWN" }
  if ($op -and $op.migration_watch_status) { $script:health["SENTINEL"] = [string]$op.migration_watch_status } else { $script:health["SENTINEL"] = "UNKNOWN" }
  if ($op -and $op.gate_status -and $op.gate_status.live_gate1) {
    $script:health["LIVE GATE-1 EVENT"] = [string]$op.gate_status.live_gate1
  } else {
    $script:health["LIVE GATE-1 EVENT"] = "UNKNOWN"
  }
  if ($op -and $op.discord) {
    if ($op.discord.policy) { $script:health["DISCORD POLICY"] = [string]$op.discord.policy }
    if ($op.discord.delivery) { $script:health["DISCORD DELIVERY"] = [string]$op.discord.delivery }
  }
  if ($op -and $op.quality_state -and $op.quality_state.current) { $script:health["QUALITY"] = [string]$op.quality_state.current }
  $rd = docker exec stinky-redis redis-cli ping 2>$null
  if ("$rd" -match "PONG") { $script:health["REDIS"] = "CONNECTED" } else { $script:health["REDIS"] = "UNKNOWN" }
  Show-HealthTable
  try { Start-Process "http://127.0.0.1:3000/operator" } catch {
    Write-Warn "browser launch failed - Genesis stays running"
  }
  try { & $psExe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "install-desktop-shortcut.ps1") | Out-Null } catch {}
  Write-StartupLog -Component "launcher" -Result "ALREADY RUNNING"
  Write-Host ""
  Write-Host "  ALREADY RUNNING. No duplicate processes started." -ForegroundColor Green
  Write-Host "  Operator:  http://127.0.0.1:3000/operator" -ForegroundColor Cyan
  exit 0
}

if ($Restart) {
  Write-Step "[0] Restart requested - stopping previous Genesis instance"
  & $psExe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "stop-stinky.ps1")
  Start-Sleep 3
}

try {
  Sync-FromGitHub
  Ensure-DotEnv
  Ensure-Venv
  Ensure-Web
  Ensure-Docker
  if ($failed) { throw "infrastructure failed" }
  Apply-Schema
  Invoke-PersistenceSmoke

  Write-Step "[services] start (detached; launcher exit does not kill them)"
  $procs = [ordered]@{}
  $procs["event-log"] = Start-DetachedSvc "event-log" "& '$venvPy' -m uvicorn event_log.api:app --port 8002 --host 127.0.0.1" -Port 8002 -Required
  Start-Sleep 3
  $procs["api"]       = Start-DetachedSvc "api" "& '$venvPy' -m stinky_api.cli" -Port 8010 -Required
  Start-Sleep 2
  $procs["sentinel"]  = Start-DetachedSvc "sentinel" "& '$venvPy' -m sentinel.cli" -Required
  Start-Sleep 1
  $procs["discord"]   = Start-DetachedSvc "discord" "& '$venvPy' -m discord_bot.cli"
  Start-Sleep 1
  $procs["collector"] = Start-DetachedSvc "collector" "& '$venvPy' -m post_migration.cli"
  Start-Sleep 1
  $procs["entities"]  = Start-DetachedSvc "entities" "& '$venvPy' -m entity_resolver.cli"
  Start-Sleep 1
  $procs["web"]       = Start-DetachedSvc "web" "Set-Location -LiteralPath (Join-Path '$root' 'apps\web'); npm run dev -- -p 3000 -H 127.0.0.1" -Port 3000 -Required
  Start-Sleep 1
  $procs["maintain"]  = Start-DetachedSvc "maintain" "while (`$true) { try { & '$venvPy' -m post_migration.cli learn-success } catch {}; try { & '$venvPy' -m post_migration.cli recompute-performance } catch {}; Start-Sleep -Seconds 21600 }"
  Write-PidFile $procs

  Write-Step "[health] real endpoints (not process-exists)"
  $elOk = Wait-Http "http://127.0.0.1:8002/health" 40
  $apiOk = Wait-Http "http://127.0.0.1:8010/health" 75
  if ($apiOk) { $script:health["BACKEND"] = "UP"; Write-Ok "BACKEND  http://127.0.0.1:8010/health" }
  else {
    $script:health["BACKEND"] = "DOWN"
    Fail-Component "BACKEND" "DOWN" "health endpoint did not respond" (Join-Path $logDir "api.log") "See logs\api.log and logs\startup.log"
  }
  if ($elOk) { Write-Ok "event-log http://127.0.0.1:8002/health" }
  else { Write-Warn "event-log not ready - see logs\event-log.log" }

  $webOk = Wait-Http "http://127.0.0.1:3000/operator" 90
  if ($webOk) { $script:health["FRONTEND"] = "UP"; Write-Ok "FRONTEND http://127.0.0.1:3000/operator" }
  else {
    $script:health["FRONTEND"] = "DOWN"
    Fail-Component "FRONTEND" "DOWN" "operator page did not respond" (Join-Path $logDir "web.log") "See logs\web.log. Browser will not be opened."
  }

  $sentPid = [int]$procs["sentinel"]
  if ($sentPid -gt 0 -and (Test-PidAlive $sentPid)) {
    $script:health["SENTINEL"] = "RUNNING"
    Write-Ok "SENTINEL process running (WS reachability is verified from the desk, not invented here)"
  } else {
    $script:health["SENTINEL"] = "DOWN"
    Write-Warn "SENTINEL process not running - see logs\sentinel.log"
  }

  $op = $null
  if ($apiOk) { $op = Get-JsonUrl "http://127.0.0.1:8010/v1/operator" }
  if ($op) {
    $script:health["OPERATOR"] = "READY"
    if ($op.system_status) { $script:health["SYSTEM"] = [string]$op.system_status }
    if ($op.database -and $op.database.status) { $script:health["DATABASE"] = [string]$op.database.status }
    if ($op.database -and $null -ne $op.database.active_watch_count) {
      $script:health["ACTIVE WATCHES"] = [string]$op.database.active_watch_count
    }
    if ($op.live_data_status) { $script:health["LIVE MARKET DATA"] = [string]$op.live_data_status } else { $script:health["LIVE MARKET DATA"] = "UNKNOWN" }
    if ($op.migration_watch_status) { $script:health["MIGRATION WATCH"] = [string]$op.migration_watch_status }
    if ($op.gate_status -and $op.gate_status.live_gate1) {
      $script:health["LIVE GATE-1 EVENT"] = [string]$op.gate_status.live_gate1
    } else {
      $script:health["LIVE GATE-1 EVENT"] = "UNKNOWN"
    }
    if ($op.discord) {
      if ($op.discord.policy) { $script:health["DISCORD POLICY"] = [string]$op.discord.policy }
      if ($op.discord.delivery) { $script:health["DISCORD DELIVERY"] = [string]$op.discord.delivery }
    }
    if ($op.quality_state -and $op.quality_state.current) { $script:health["QUALITY"] = [string]$op.quality_state.current }
  } else {
    if ($apiOk) { $script:health["OPERATOR"] = "NOT READY" } else { $script:health["OPERATOR"] = "NOT READY" }
    if (-not $script:health.Contains("SYSTEM")) { $script:health["SYSTEM"] = "UNKNOWN" }
    if (-not $script:health.Contains("LIVE MARKET DATA")) { $script:health["LIVE MARKET DATA"] = "UNKNOWN" }
    if (-not $script:health.Contains("LIVE GATE-1 EVENT")) { $script:health["LIVE GATE-1 EVENT"] = "UNKNOWN" }
    if (-not $script:health.Contains("ACTIVE WATCHES")) { $script:health["ACTIVE WATCHES"] = "UNKNOWN" }
  }

  if (-not $script:health.Contains("DATABASE")) { $script:health["DATABASE"] = "UNKNOWN" }
  if (-not $script:health.Contains("REDIS")) { $script:health["REDIS"] = "UNKNOWN" }
  if (-not $script:health.Contains("SYSTEM")) { $script:health["SYSTEM"] = "UNKNOWN" }
  if (-not $script:health.Contains("ACTIVE WATCHES")) { $script:health["ACTIVE WATCHES"] = "UNKNOWN" }

  Show-HealthTable
  Write-StartupLog -Component "health" -Result $(if ($failed) { "FAILED" } else { "ok" }) -Reason (($script:health.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join ",")

  if ($webOk) {
    Write-Step "[ui] open operator desk (frontend is actually ready)"
    try { Start-Process "http://127.0.0.1:3000/operator" }
    catch {
      Write-Warn "browser launch failed - Genesis itself continues running"
      Write-StartupLog -Component "browser" -Result "failed" -Reason $_.Exception.Message
    }
  } else {
    Write-Warn "browser not opened because frontend is not ready"
  }

  try { & $psExe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "install-desktop-shortcut.ps1") | Out-Null } catch {}

  Write-Host ""
  if ($failed) {
    Write-Host "  NOT READY. Services that started remain up. Fix the failed component." -ForegroundColor Red
    Write-Host "  Log: $startupLog" -ForegroundColor Yellow
    exit 1
  }
  Write-Host "  READY. Services stay up after this window closes." -ForegroundColor Green
  Write-Host "  Operator:  http://127.0.0.1:3000/operator" -ForegroundColor Cyan
  Write-Host "  Command:   http://127.0.0.1:3000/command-center" -ForegroundColor Cyan
  Write-Host "  Stop:      double-click  Stop Genesis  on the desktop" -ForegroundColor Yellow
  Write-Host "  LIVE GATE-1 is NOT OBSERVED until a real 150k USD / 5m print." -ForegroundColor DarkGray
  Write-Host "  Log: $startupLog" -ForegroundColor DarkGray
  Write-Host ""
  Write-StartupLog -Component "launcher" -Result "READY"
  exit 0
} catch {
  Fail-Component "launcher" "DOWN" $_.Exception.Message $startupLog "Read the error above, then retry. Services already started were not killed."
  Show-HealthTable
  exit 1
}
