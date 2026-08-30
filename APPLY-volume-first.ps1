# Overlay volume-first-v1 onto D:\Work\Project-Genesis
# Usage (from the extracted overlay folder):
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\APPLY-volume-first.ps1

$ErrorActionPreference = "Stop"
$src = $PSScriptRoot
$dst = "D:\Work\Project-Genesis"
if (-not (Test-Path $dst)) { throw "Project not found: $dst" }

$paths = @(
  "packages\stinky-core\src\stinky_core\admission.py",
  "packages\stinky-core\src\stinky_core\inspect.py",
  "packages\stinky-core\src\stinky_core\intelligence.py",
  "packages\stinky-core\src\stinky_core\backtest.py",
  "packages\stinky-core\src\stinky_core\__init__.py",
  "packages\stinky-core\src\stinky_core\events\base.py",
  "packages\stinky-core\tests\test_admission.py",
  "packages\stinky-core\tests\test_eligibility_matrix.py",
  "packages\stinky-core\tests\test_intelligence.py",
  "packages\stinky-core\tests\test_fee_resolver.py",
  "services\sentinel\src\sentinel\volume.py",
  "services\sentinel\src\sentinel\discovery.py",
  "services\sentinel\src\sentinel\durable.py",
  "services\sentinel\src\sentinel\qualify.py",
  "services\sentinel\src\sentinel\filter_engine.py",
  "services\sentinel\src\sentinel\config.py",
  "services\sentinel\migrations\005_market_inspections.sql",
  "services\sentinel\tests\test_filter_engine.py",
  "services\sentinel\tests\test_qualify_fees_gate.py",
  "services\api\src\stinky_api\queries.py",
  "services\api\src\stinky_api\main.py",
  "services\discord-bot\src\discord_bot\alerter.py",
  "services\discord-bot\tests\test_quality_gate.py",
  "services\replay\src\stinky_replay\engine.py",
  "apps\web\src\components\command-center\CommandCenter.tsx",
  "docs\FILTER_ENGINE.md",
  "docs\FILTER_CONTRACT.md",
  "docs\adr\ADR-009-fee-resolver.md",
  "docs\adr\ADR-010-volume-first-intelligence.md"
)

foreach ($rel in $paths) {
  $from = Join-Path $src $rel
  $to = Join-Path $dst $rel
  if (-not (Test-Path $from)) {
    Write-Host "SKIP $rel" -ForegroundColor Yellow
    continue
  }
  $dir = Split-Path $to -Parent
  if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
  Copy-Item -Force $from $to
  Write-Host "OK $rel" -ForegroundColor Green
}

$envFile = Join-Path $dst ".env"
if (Test-Path $envFile) {
  $c = Get-Content $envFile -Raw
  if ($c -match "STINKY_GATE1_VOLUME_5M_USD=") {
    $c = $c -replace "STINKY_GATE1_VOLUME_5M_USD=\S+", "STINKY_GATE1_VOLUME_5M_USD=150000"
  } else {
    $c = $c.TrimEnd() + "`r`nSTINKY_GATE1_VOLUME_5M_USD=150000`r`n"
  }
  if ($c -match "STINKY_MIN_VOLUME_USD=") {
    $c = $c -replace "STINKY_MIN_VOLUME_USD=\S+", "STINKY_MIN_VOLUME_USD=150000"
  } else {
    $c = $c.TrimEnd() + "`r`nSTINKY_MIN_VOLUME_USD=150000`r`n"
  }
  if ($c -match "STINKY_FILTER_VERSION=") {
    $c = $c -replace "STINKY_FILTER_VERSION=\S+", "STINKY_FILTER_VERSION=volume-first-v1.0.0"
  } else {
    $c = $c.TrimEnd() + "`r`nSTINKY_FILTER_VERSION=volume-first-v1.0.0`r`n"
  }
  if ($c -match "STINKY_ENABLE_HELIUS=") {
    $c = $c -replace "STINKY_ENABLE_HELIUS=\S+", "STINKY_ENABLE_HELIUS=false"
  }
  Set-Content -Path $envFile -Value $c -NoNewline
  Write-Host "OK .env Gate 1 150k (no secrets added)" -ForegroundColor Green
}

Write-Host "DONE volume-first-v1.0.0" -ForegroundColor Green
Write-Host "Gate 1 is an investigation trigger, not a buy signal."
