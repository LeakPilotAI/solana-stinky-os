# Overlay harden-v1.1.0 onto D:\Work\Project-Genesis
# Usage (from the extracted overlay folder):
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\APPLY-harden.ps1

$ErrorActionPreference = "Stop"
$src = $PSScriptRoot
$dst = "D:\Work\Project-Genesis"
if (-not (Test-Path $dst)) { throw "Project not found: $dst" }

$paths = @(
  "packages\stinky-core\src\stinky_core\admission.py",
  "packages\stinky-core\src\stinky_core\inspect.py",
  "packages\stinky-core\src\stinky_core\intelligence.py",
  "packages\stinky-core\src\stinky_core\backtest.py",
  "packages\stinky-core\src\stinky_core\fees.py",
  "packages\stinky-core\tests\test_hardening.py",
  "packages\stinky-core\tests\test_admission.py",
  "packages\stinky-core\tests\test_intelligence.py",
  "packages\stinky-core\tests\test_eligibility_matrix.py",
  "services\sentinel\src\sentinel\qualify.py",
  "services\sentinel\src\sentinel\discovery.py",
  "services\sentinel\tests\test_qualify_fees_gate.py",
  "services\discord-bot\src\discord_bot\alerter.py",
  "services\replay\src\stinky_replay\engine.py",
  "apps\web\src\components\command-center\CommandCenter.tsx",
  "apps\web\src\lib\api\client.ts",
  "apps\web\src\app\alerts\page.tsx",
  "docs\FILTER_ENGINE.md",
  "docs\FILTER_CONTRACT.md",
  "docs\adr\ADR-011-hardening-fail-closed.md"
)

foreach ($rel in $paths) {
  $from = Join-Path $src $rel
  $to = Join-Path $dst $rel
  if (-not (Test-Path $from)) { Write-Warning "Missing in overlay: $rel"; continue }
  $dir = Split-Path $to -Parent
  if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
  Copy-Item -Force $from $to
  Write-Host "applied $rel"
}

Write-Host "Harden overlay applied. Restart Stinky OS. No .env copied."
