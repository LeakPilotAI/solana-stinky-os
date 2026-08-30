# Overlay intel-v1.3.0-failclosed onto D:\Work\Project-Genesis
# Usage (from the extracted overlay folder):
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\APPLY-intel.ps1

$ErrorActionPreference = "Stop"
$src = $PSScriptRoot
$dst = "D:\Work\Project-Genesis"
if (-not (Test-Path $dst)) { throw "Project not found: $dst" }

$paths = @(
  "packages\stinky-core\src\stinky_core\memory.py",
  "packages\stinky-core\src\stinky_core\fingerprint.py",
  "packages\stinky-core\src\stinky_core\evidence.py",
  "packages\stinky-core\src\stinky_core\dataset.py",
  "packages\stinky-core\src\stinky_core\inspect.py",
  "packages\stinky-core\src\stinky_core\intelligence.py",
  "packages\stinky-core\src\stinky_core\backtest.py",
  "packages\stinky-core\src\stinky_core\outcomes.py",
  "packages\stinky-core\src\stinky_core\admission.py",
  "packages\stinky-core\tests\test_memory.py",
  "packages\stinky-core\tests\test_intelligence.py",
  "packages\stinky-core\tests\test_hardening.py",
  "packages\stinky-core\tests\test_eligibility_matrix.py",
  "services\sentinel\src\sentinel\durable.py",
  "services\sentinel\src\sentinel\volume.py",
  "services\sentinel\migrations\006_intelligence_memory.sql",
  "services\api\src\stinky_api\main.py",
  "docs\FILTER_ENGINE.md",
  "docs\adr\ADR-012-asof-intelligence-memory.md",
  "docs\adr\ADR-013-unknown-is-not-bullish.md"
)

foreach ($rel in $paths) {
  $from = Join-Path $src $rel
  $to = Join-Path $dst $rel
  if (-not (Test-Path $from)) { throw "Missing overlay file: $rel" }
  $parent = Split-Path -Parent $to
  if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
  Copy-Item -Force $from $to
  Write-Host "applied $rel"
}

Write-Host ""
Write-Host "Applied intel-v1.3.0-failclosed. Restart:"
Write-Host "  powershell -File D:\Work\Project-Genesis\stop-stinky.ps1"
Write-Host "  powershell -File D:\Work\Project-Genesis\start-stinky.ps1"
Write-Host "Verify: Gate 1 unchanged at `$150k. UNKNOWN does not promote. Volume is not bullish."
