# stop-stinky.ps1 - stop Genesis-owned apps and Genesis docker compose.
# Does NOT quit Docker Desktop. Does NOT kill ATLAS.
# Never kills generic python / node / npm / redis / postgres / docker
# unless the process command line is positively Genesis-owned.
$ErrorActionPreference = "Continue"

function Get-ScriptRoot {
  if ($PSScriptRoot) { return $PSScriptRoot }
  if ($MyInvocation.MyCommand.Path) { return (Split-Path -Parent $MyInvocation.MyCommand.Path) }
  return (Get-Location).Path
}

function Restore-SearchPath {
  try {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $parts = @()
    if ($machine) { $parts += $machine }
    if ($user) { $parts += $user }
    if ($env:Path) { $parts += $env:Path }
    if ($parts.Count -gt 0) { $env:Path = ($parts -join ";") }
  } catch {}
  $extras = @(
    (Join-Path $env:ProgramFiles "Git\cmd"),
    (Join-Path $env:ProgramFiles "Git\bin"),
    (Join-Path $env:ProgramFiles "Docker\Docker\resources\bin"),
    (Join-Path $env:ProgramFiles "nodejs")
  )
  foreach ($d in $extras) {
    if ($d -and (Test-Path -LiteralPath $d) -and ($env:Path -notlike ("*" + $d + "*"))) {
      $env:Path = $d + ";" + $env:Path
    }
  }
}

Restore-SearchPath

$here = Get-ScriptRoot
$operatorRoot = "D:\Work\Project-Genesis"
if (Test-Path -LiteralPath (Join-Path $here "docker-compose.yml")) {
  $root = $here
} elseif (Test-Path -LiteralPath (Join-Path $operatorRoot "docker-compose.yml")) {
  $root = $operatorRoot
} else {
  $root = $here
}

$logDir = Join-Path $root "logs"
$pidFile = Join-Path $logDir "stinky-pids.txt"
$startupLog = Join-Path $logDir "startup.log"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
if (Test-Path -LiteralPath $root) { Set-Location -LiteralPath $root }

Write-Host "STOPPING Genesis (owned processes only)..." -ForegroundColor Yellow
Write-Host "  $root" -ForegroundColor DarkGray

function Write-StartupLog([string]$Component, [string]$Result, [string]$Reason = "", [string]$PidValue = "") {
  $ts = Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"
  $line = "$ts  stop:$Component  $Result"
  if ($PidValue) { $line += "  pid=$PidValue" }
  if ($Reason) { $line += "  reason=$Reason" }
  Add-Content -LiteralPath $startupLog -Value $line -Encoding ascii
}

function Test-GenesisOwned([int]$Id) {
  if ($Id -le 0) { return $false }
  try {
    $p = Get-CimInstance Win32_Process -Filter "ProcessId=$Id" -ErrorAction SilentlyContinue
    if (-not $p) { return $false }
    $n = [string]$p.Name
    if ($n -match "(?i)^docker|Docker Desktop|com\.docker|dockerd") { return $false }
    $c = [string]$p.CommandLine
    if (-not $c) { return $false }
    $rootEsc = [regex]::Escape($root)
    if ($c -match $rootEsc) { return $true }
    if ($c -match "Project-Genesis") { return $true }
    if ($c -match "solana-stinky-os") { return $true }
    if ($c -match "run-(event-log|api|sentinel|discord|collector|entities|web|maintain)\.ps1") { return $true }
    if ($c -match "genesis-(event-log|api|sentinel|discord|collector|entities|web|maintain)") { return $true }
    return $false
  } catch { return $false }
}

function Stop-OwnedPid([int]$Id) {
  if ($Id -le 0) { return }
  try {
    $p = Get-CimInstance Win32_Process -Filter "ProcessId=$Id" -ErrorAction SilentlyContinue
    if ($p -and $p.Name -match "(?i)docker|Docker Desktop|com\.docker") {
      Write-Host "  skip docker pid $Id" -ForegroundColor DarkGray
      return
    }
  } catch {}
  if (-not (Test-GenesisOwned $Id)) {
    Write-Host "  skip pid $Id (not Genesis-owned)" -ForegroundColor DarkGray
    Write-StartupLog "pid" "skipped" "not Genesis-owned" "$Id"
    return
  }
  Write-Host "  taskkill /PID $Id /T" -ForegroundColor Yellow
  Write-StartupLog "pid" "killed" "" "$Id"
  taskkill /PID $Id /T /F 2>$null | Out-Null
}

if (Test-Path -LiteralPath $pidFile) {
  Get-Content -LiteralPath $pidFile | ForEach-Object {
    if ($_ -match "=(\d+)\s*$") { Stop-OwnedPid ([int]$Matches[1]) }
    elseif ($_ -match "^\d+$") { Stop-OwnedPid ([int]$_) }
  }
  Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
}

try {
  Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | ForEach-Object {
    $id = [int]$_.ProcessId
    $c = [string]$_.CommandLine
    if (-not $c) { return }
    if ($c -match "(?i)docker|Docker Desktop") { return }
    $rootEsc = [regex]::Escape($root)
    $ownedPath = ($c -match $rootEsc) -or ($c -match "Project-Genesis")
    if (-not $ownedPath) { return }
    if ($c -match "uvicorn|stinky-|next dev|npm run|event_log|stinky_api|sentinel\.cli|discord_bot|post_migration|entity_resolver|run-(event-log|api|sentinel|discord|collector|entities|web|maintain)\.ps1") {
      Stop-OwnedPid $id
    }
  }
} catch {}

# Genesis-owned ports only. Never ATLAS (8001) or shared 5432/6379.
# Never kill a listener unless the owning process is Genesis-owned.
foreach ($port in 8002, 8010, 3000) {
  try {
    $conns = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    foreach ($c in $conns) {
      $id = [int]$c.OwningProcess
      if (Test-GenesisOwned $id) { Stop-OwnedPid $id }
      else { Write-Host "  skip port $port pid $id (not Genesis-owned)" -ForegroundColor DarkGray }
    }
  } catch {}
}

Start-Sleep 2
if (Test-Path -LiteralPath (Join-Path $root "docker-compose.yml")) {
  Write-Host "Stopping Genesis containers (volumes kept, Docker Desktop not quit)..." -ForegroundColor Yellow
  $docker = $null
  $dc = Get-Command docker -ErrorAction SilentlyContinue
  if ($dc -and $dc.Source) { $docker = [string]$dc.Source }
  elseif (Test-Path -LiteralPath (Join-Path $env:ProgramFiles "Docker\Docker\resources\bin\docker.exe")) {
    $docker = Join-Path $env:ProgramFiles "Docker\Docker\resources\bin\docker.exe"
  }
  if ($docker) {
    & $docker compose -f "$root\docker-compose.yml" stop 2>$null
  } else {
    docker compose -f "$root\docker-compose.yml" stop 2>$null
  }
  Write-StartupLog "docker-compose" "stopped" "genesis compose project only"
}
Write-Host "STOPPED." -ForegroundColor Green
Write-StartupLog "launcher" "STOPPED"
exit 0
