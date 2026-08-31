# Allowlisted Genesis service runner. Static file, no downloads, no generated scripts.
# Started by scripts\start-genesis-svc.cmd (cmd START /MIN) so the Explorer job cannot kill it.
param(
  [Parameter(Mandatory = $true)]
  [ValidateSet("event-log", "api", "sentinel", "discord", "collector", "entities", "web", "maintain")]
  [string]$Name
)

$ErrorActionPreference = "Continue"

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
  $pf = $env:ProgramFiles
  $la = $env:LOCALAPPDATA
  $extras = @(
    (Join-Path $pf "Git\cmd"),
    (Join-Path $pf "Docker\Docker\resources\bin"),
    (Join-Path $pf "nodejs"),
    (Join-Path $la "Programs\nodejs"),
    (Join-Path $env:APPDATA "npm")
  )
  foreach ($d in $extras) {
    if ($d -and (Test-Path -LiteralPath $d) -and ($env:Path -notlike ("*" + $d + "*"))) {
      $env:Path = $d + ";" + $env:Path
    }
  }
}

Restore-SearchPath

$root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path -LiteralPath (Join-Path $root "docker-compose.yml"))) {
  $root = "D:\Work\Project-Genesis"
}
Set-Location -LiteralPath $root

$logDir = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ($Name + ".log")

$venvPy = Join-Path $root ".venv\Scripts\python.exe"
$activate = Join-Path $root ".venv\Scripts\Activate.ps1"
if (Test-Path -LiteralPath $activate) { & $activate }

$pyPath = @(
  (Join-Path $root "packages\stinky-core\src"),
  (Join-Path $root "services\event-log\src"),
  (Join-Path $root "services\api\src"),
  (Join-Path $root "services\sentinel\src"),
  (Join-Path $root "services\discord-bot\src"),
  (Join-Path $root "services\post-migration-collector\src"),
  (Join-Path $root "services\entity-resolver\src")
) -join ";"
$env:PYTHONPATH = $pyPath + ";" + $env:PYTHONPATH
$env:BROWSER = "none"
$env:STINKY_ROOT = $root

function Get-NpmCmd {
  $c = Get-Command npm -ErrorAction SilentlyContinue
  if ($c -and $c.Source) { return [string]$c.Source }
  $hits = @(
    (Join-Path $env:ProgramFiles "nodejs\npm.cmd"),
    (Join-Path $env:LOCALAPPDATA "Programs\nodejs\npm.cmd")
  )
  foreach ($h in $hits) {
    if ($h -and (Test-Path -LiteralPath $h)) { return $h }
  }
  return $null
}

Write-Host ("=== " + $Name + " pid=" + $PID)
Add-Content -LiteralPath $log -Value ("[" + (Get-Date -Format o) + "] start pid=" + $PID)

try {
  switch ($Name) {
    "event-log" {
      & $venvPy -m uvicorn event_log.api:app --port 8002 --host 127.0.0.1 2>&1 | Tee-Object -FilePath $log -Append
    }
    "api" {
      & $venvPy -m stinky_api.cli 2>&1 | Tee-Object -FilePath $log -Append
    }
    "sentinel" {
      & $venvPy -m sentinel.cli 2>&1 | Tee-Object -FilePath $log -Append
    }
    "discord" {
      & $venvPy -m discord_bot.cli 2>&1 | Tee-Object -FilePath $log -Append
    }
    "collector" {
      & $venvPy -m post_migration.cli 2>&1 | Tee-Object -FilePath $log -Append
    }
    "entities" {
      & $venvPy -m entity_resolver.cli 2>&1 | Tee-Object -FilePath $log -Append
    }
    "web" {
      $npm = Get-NpmCmd
      Set-Location -LiteralPath (Join-Path $root "apps\web")
      if ($npm) {
        & $npm run dev -- -p 3000 -H 127.0.0.1 2>&1 | Tee-Object -FilePath $log -Append
      } else {
        npm run dev -- -p 3000 -H 127.0.0.1 2>&1 | Tee-Object -FilePath $log -Append
      }
    }
    "maintain" {
      while ($true) {
        try { & $venvPy -m post_migration.cli learn-success 2>&1 | Tee-Object -FilePath $log -Append } catch {}
        try { & $venvPy -m post_migration.cli recompute-performance 2>&1 | Tee-Object -FilePath $log -Append } catch {}
        Start-Sleep -Seconds 21600
      }
    }
  }
} finally {
  Add-Content -LiteralPath $log -Value ("[" + (Get-Date -Format o) + "] exit LASTEXITCODE=" + $LASTEXITCODE)
}
