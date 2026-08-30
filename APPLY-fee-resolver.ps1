# Overlay fee-resolver-v1 onto D:\Work\Project-Genesis
# Usage (from the extracted overlay folder):
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\APPLY-fee-resolver.ps1

$ErrorActionPreference = "Stop"
$src = $PSScriptRoot
$dst = "D:\Work\Project-Genesis"
if (-not (Test-Path $dst)) { throw "Project not found: $dst" }

$paths = @(
  "packages\stinky-core\src\stinky_core\fees.py",
  "packages\stinky-core\src\stinky_core\admission.py",
  "packages\stinky-core\src\stinky_core\backtest.py",
  "packages\stinky-core\src\stinky_core\__init__.py",
  "packages\stinky-core\tests\test_fee_resolver.py",
  "packages\stinky-core\tests\test_eligibility_matrix.py",
  "packages\stinky-core\tests\test_admission.py",
  "packages\stinky-core\tests\fixtures\pump_amm_fee_tx.json",
  "services\sentinel\src\sentinel\volume.py",
  "services\sentinel\src\sentinel\discovery.py",
  "services\sentinel\src\sentinel\durable.py",
  "services\sentinel\src\sentinel\qualify.py",
  "services\sentinel\src\sentinel\filter_engine.py",
  "services\sentinel\src\sentinel\config.py",
  "services\sentinel\migrations\004_fee_observations.sql",
  "services\sentinel\tests\test_qualify_fees_gate.py",
  "services\api\src\stinky_api\queries.py",
  "services\api\src\stinky_api\main.py",
  "services\discord-bot\src\discord_bot\alerter.py",
  "services\discord-bot\tests\test_quality_gate.py",
  "services\replay\src\stinky_replay\engine.py",
  "docs\FILTER_ENGINE.md",
  "docs\FILTER_CONTRACT.md",
  "docs\adr\ADR-009-fee-resolver.md"
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
  if ($c -match "STINKY_MIN_FEES_SOL=") {
    $c = $c -replace "STINKY_MIN_FEES_SOL=\S+", "STINKY_MIN_FEES_SOL=1"
  } else {
    $c = $c.TrimEnd() + "`r`nSTINKY_MIN_FEES_SOL=1`r`n"
  }
  if ($c -match "STINKY_ENABLE_HELIUS=") {
    $c = $c -replace "STINKY_ENABLE_HELIUS=\S+", "STINKY_ENABLE_HELIUS=false"
  }
  Set-Content -Path $envFile -Value $c -NoNewline
  Write-Host "OK .env thresholds (keys not printed)" -ForegroundColor Green
}

Write-Host "Done. Restart Stinky OS so the fee resolver + canonical gate load." -ForegroundColor Cyan
