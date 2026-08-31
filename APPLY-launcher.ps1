# APPLY-launcher.ps1
# VS Code one-shot: pull origin/main, overwrite launcher files, remake Genesis.lnk.
# Does NOT start the stack. After this, double-click Genesis.
# ASCII only. Windows PowerShell 5.1.
#
# In VS Code terminal (D:\Work\Project-Genesis):
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\APPLY-launcher.ps1
param(
  [switch]$Start
)

$ErrorActionPreference = "Continue"
$repo = "https://github.com/LeakPilotAI/solana-stinky-os.git"
$operatorRoot = "D:\Work\Project-Genesis"

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
  $pf = $env:ProgramFiles
  $pfx86 = ${env:ProgramFiles(x86)}
  $la = $env:LOCALAPPDATA
  $extras = @(
    (Join-Path $pf "Git\cmd"),
    (Join-Path $pf "Git\bin"),
    (Join-Path $pf "Docker\Docker\resources\bin"),
    (Join-Path $pf "nodejs"),
    (Join-Path $la "Programs\Git\cmd"),
    (Join-Path $la "Programs\nodejs"),
    (Join-Path $la "Programs\Python\Launcher"),
    (Join-Path $la "Programs\Python\Python312"),
    (Join-Path $la "Programs\Python\Python312\Scripts"),
    "C:\Python312",
    "C:\Python312\Scripts"
  )
  if ($pfx86) { $extras += (Join-Path $pfx86 "Git\cmd") }
  foreach ($d in $extras) {
    if ($d -and (Test-Path -LiteralPath $d) -and ($env:Path -notlike ("*" + $d + "*"))) {
      $env:Path = $d + ";" + $env:Path
    }
  }
}

Restore-SearchPath

$here = Get-ScriptRoot
if (Test-Path -LiteralPath (Join-Path $here "docker-compose.yml")) {
  $root = $here
} elseif (Test-Path -LiteralPath (Join-Path $operatorRoot "docker-compose.yml")) {
  $root = $operatorRoot
} else {
  $root = $operatorRoot
}

$logDir = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$applyLog = Join-Path $logDir "launcher-apply.log"
$psExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
if (-not (Test-Path -LiteralPath $psExe)) { $psExe = "powershell.exe" }

function Write-Apply([string]$Msg) {
  $line = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssK") + "  " + $Msg
  Add-Content -LiteralPath $applyLog -Value $line -Encoding ascii
  Write-Host "  $Msg"
}

Write-Host ""
Write-Host "  GENESIS APPLY LAUNCHER" -ForegroundColor Cyan
Write-Host "  $root"
Write-Host "  Pull origin/main, remake Genesis.lnk, do not invent Gate 1." -ForegroundColor DarkGray
Write-Host ""
Write-Apply ("begin root=" + $root + " ps=" + $PSVersionTable.PSVersion.ToString())

$git = Get-Command git -ErrorAction SilentlyContinue
if (-not $git) {
  Write-Host "  git is not on PATH. Install Git for Windows, then re-run this file." -ForegroundColor Red
  Write-Apply "FAIL git missing"
  exit 1
}
Write-Apply ("git=" + $git.Source)

$envFile = Join-Path $root ".env"
$envBak = Join-Path $env:TEMP "genesis-env-backup"
if (Test-Path -LiteralPath $envFile) {
  Copy-Item -Force -LiteralPath $envFile -Destination $envBak
  Write-Apply "backed up .env"
}

New-Item -ItemType Directory -Force -Path $root | Out-Null
Set-Location -LiteralPath $root

if (Test-Path -LiteralPath (Join-Path $root ".git")) {
  Write-Host "  git fetch + reset --hard origin/main (.env kept)" -ForegroundColor Yellow
  git -C $root remote set-url origin $repo 2>$null
  git -C $root fetch origin 2>&1 | Out-Host
  if ($LASTEXITCODE -ne 0) {
    Write-Host "  git fetch failed. Check network / GitHub access." -ForegroundColor Red
    Write-Apply "FAIL git fetch"
    exit 1
  }
  git -C $root reset --hard origin/main 2>&1 | Out-Host
  git -C $root checkout -f -B main origin/main 2>&1 | Out-Host
} elseif (Test-Path -LiteralPath $root) {
  Write-Host "  folder exists but is not git - overlay from clone" -ForegroundColor Yellow
  $tmp = Join-Path $env:TEMP "genesis-launcher-src"
  if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
  git clone --depth 1 $repo $tmp
  if ($LASTEXITCODE -ne 0) {
    Write-Host "  git clone failed." -ForegroundColor Red
    Write-Apply "FAIL git clone"
    exit 1
  }
  & robocopy $tmp $root /E /XD .git .venv node_modules logs dumps .next __pycache__ /XF .env /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
  if (-not (Test-Path (Join-Path $root ".git"))) {
    Copy-Item -Recurse -Force (Join-Path $tmp ".git") (Join-Path $root ".git")
  }
} else {
  Write-Host "  cloning $repo" -ForegroundColor Yellow
  git clone --depth 1 $repo $root
  if ($LASTEXITCODE -ne 0) {
    Write-Host "  git clone failed." -ForegroundColor Red
    Write-Apply "FAIL git clone"
    exit 1
  }
}

$head = ""
try { $head = (git -C $root rev-parse --short HEAD) } catch {}
Write-Host ("  tree = " + $head) -ForegroundColor Green
Write-Apply ("tree=" + $head)

if (Test-Path -LiteralPath $envBak) {
  Copy-Item -Force -LiteralPath $envBak -Destination (Join-Path $root ".env")
  Write-Apply "restored .env"
} elseif (-not (Test-Path -LiteralPath (Join-Path $root ".env"))) {
  if (Test-Path -LiteralPath (Join-Path $root ".env.example")) {
    Copy-Item (Join-Path $root ".env.example") (Join-Path $root ".env")
    Write-Apply "created .env from example"
  }
}

$installer = Join-Path $root "install-desktop-shortcut.ps1"
if (-not (Test-Path -LiteralPath $installer)) {
  Write-Host "  MISSING $installer after pull." -ForegroundColor Red
  Write-Apply "FAIL missing installer"
  exit 1
}

Write-Host "  remaking desktop shortcuts (cmd.exe /d /k, absolute paths)" -ForegroundColor Yellow
& $psExe -NoProfile -ExecutionPolicy Bypass -File $installer
if ($LASTEXITCODE -ne 0) {
  Write-Host "  shortcut installer exited $LASTEXITCODE" -ForegroundColor Red
  Write-Apply ("FAIL installer exit=" + $LASTEXITCODE)
  exit 1
}

$ws = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath("Desktop")
$candidates = @(
  (Join-Path $desktop "Genesis.lnk"),
  (Join-Path $env:USERPROFILE "Desktop\Genesis.lnk"),
  (Join-Path $env:USERPROFILE "OneDrive\Desktop\Genesis.lnk")
)
$verified = $false
foreach ($lnk in $candidates) {
  if (-not (Test-Path -LiteralPath $lnk)) { continue }
  $sc = $ws.CreateShortcut($lnk)
  Write-Host ""
  Write-Host ("  VERIFY " + $lnk) -ForegroundColor Cyan
  Write-Host ("    TargetPath = " + $sc.TargetPath)
  Write-Host ("    Arguments  = " + $sc.Arguments)
  Write-Host ("    WorkDir    = " + $sc.WorkingDirectory)
  Write-Apply ("lnk=" + $lnk + " target=" + $sc.TargetPath + " args=" + $sc.Arguments + " cwd=" + $sc.WorkingDirectory)
  if ($sc.TargetPath -match "cmd\.exe" -and $sc.Arguments -match "/d /k" -and $sc.WorkingDirectory) {
    $verified = $true
  } else {
    Write-Host "    SHORTCUT IS WRONG. Target must be cmd.exe with /d /k." -ForegroundColor Red
  }
}

if (-not $verified) {
  Write-Host ""
  Write-Host "  Could not verify Genesis.lnk. Recreate failed." -ForegroundColor Red
  Write-Apply "FAIL shortcut verify"
  exit 1
}

Write-Host ""
Write-Host "  READY. Desktop Genesis.lnk now points at cmd.exe /d /k." -ForegroundColor Green
Write-Host "  Double-click  Genesis  on the desktop." -ForegroundColor Cyan
Write-Host "  Window stays open. Closing it does not stop Genesis." -ForegroundColor DarkGray
Write-Host ("  Log: " + $applyLog) -ForegroundColor DarkGray
Write-Apply "READY"

if ($Start) {
  Write-Host "  starting Genesis (-SkipSync)..." -ForegroundColor Yellow
  & $psExe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "start-stinky.ps1") -SkipSync
}

exit 0
