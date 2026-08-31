# APPLY-refresh.ps1 - overwrite D:\Work\Project-Genesis from GitHub.
# Preserves .env. Recreates desktop launcher. Starts Genesis.
# ASCII only. No nested cmd /c quotes (Windows PowerShell 5.1 parser).

$ErrorActionPreference = "Continue"
$root = "D:\Work\Project-Genesis"
$repo = "https://github.com/LeakPilotAI/solana-stinky-os.git"

Write-Host ""
Write-Host "  GENESIS refresh -> $root" -ForegroundColor Cyan
Write-Host "  .env is kept. Gate 1 stays 150k USD." -ForegroundColor DarkGray
Write-Host ""

New-Item -ItemType Directory -Force -Path (Split-Path $root) | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $root "logs") | Out-Null

$envFile = Join-Path $root ".env"
$envBak = Join-Path $env:TEMP "genesis-env-backup"
if (Test-Path -LiteralPath $envFile) {
  Copy-Item -Force -LiteralPath $envFile -Destination $envBak
  Write-Host "  backed up .env" -ForegroundColor Green
}

$stop = Join-Path $root "stop-stinky.ps1"
if (Test-Path $stop) {
  Write-Host "  stopping running instance..." -ForegroundColor Yellow
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $stop
  Start-Sleep 2
}

if (Test-Path (Join-Path $root ".git")) {
  Write-Host "  git fetch + reset --hard origin/main" -ForegroundColor Yellow
  git -C $root remote set-url origin $repo
  git -C $root fetch origin
  # reset first so a dirty tree cannot abort checkout
  git -C $root reset --hard origin/main
  git -C $root checkout -f -B main origin/main
} elseif (Test-Path $root) {
  Write-Host "  folder exists but is not git - overlay from clone" -ForegroundColor Yellow
  $tmp = Join-Path $env:TEMP "genesis-fresh"
  if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
  git clone --depth 1 $repo $tmp
  & robocopy $tmp $root /E /XD .git .venv node_modules logs dumps .next __pycache__ /XF .env /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
  if ($LASTEXITCODE -ge 8) { Write-Host "  robocopy exit $LASTEXITCODE" -ForegroundColor Yellow }
  if (-not (Test-Path (Join-Path $root ".git"))) {
    Copy-Item -Recurse -Force (Join-Path $tmp ".git") (Join-Path $root ".git")
  }
} else {
  Write-Host "  cloning $repo" -ForegroundColor Yellow
  git clone --depth 1 $repo $root
}

if (Test-Path -LiteralPath $envBak) {
  Copy-Item -Force -LiteralPath $envBak -Destination (Join-Path $root ".env")
  Write-Host "  restored .env" -ForegroundColor Green
} elseif (-not (Test-Path (Join-Path $root ".env"))) {
  Copy-Item (Join-Path $root ".env.example") (Join-Path $root ".env")
  Write-Host "  created .env from example" -ForegroundColor Yellow
}

Write-Host "  installing desktop shortcuts" -ForegroundColor Yellow
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "install-desktop-shortcut.ps1")

Write-Host "  starting Genesis" -ForegroundColor Yellow
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "start-stinky.ps1") -SkipSync
Write-Host "  DONE. Use the Genesis desktop icon next time." -ForegroundColor Green
