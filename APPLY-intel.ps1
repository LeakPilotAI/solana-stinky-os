# Overlay intel-v1.10.0-live-validation onto D:\Work\Project-Genesis
# Usage (from the extracted overlay folder):
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\APPLY-intel.ps1

$ErrorActionPreference = "Stop"
$src = $PSScriptRoot
$dst = "D:\Work\Project-Genesis"
if (-not (Test-Path $dst)) { throw "Project not found: $dst" }

$paths = @(
  "packages\stinky-core\src\stinky_core\identity.py",
  "packages\stinky-core\src\stinky_core\pools.py",
  "packages\stinky-core\src\stinky_core\memory.py",
  "packages\stinky-core\src\stinky_core\fingerprint.py",
  "packages\stinky-core\src\stinky_core\sqlstore.py",
  "packages\stinky-core\src\stinky_core\book.py",
  "packages\stinky-core\src\stinky_core\dataset.py",
  "packages\stinky-core\src\stinky_core\intelligence.py",
  "packages\stinky-core\src\stinky_core\backtest.py",
  "packages\stinky-core\src\stinky_core\outcomes.py",
  "packages\stinky-core\src\stinky_core\admission.py",
  "packages\stinky-core\src\stinky_core\reputation.py",
  "packages\stinky-core\src\stinky_core\similarity.py",
  "packages\stinky-core\src\stinky_core\metrics.py",
  "packages\stinky-core\src\stinky_core\evidence.py",
  "packages\stinky-core\src\stinky_core\stages.py",
  "packages\stinky-core\src\stinky_core\observation.py",
  "packages\stinky-core\src\stinky_core\recipes.py",
  "packages\stinky-core\src\stinky_core\insights.py",
  "packages\stinky-core\src\stinky_core\quality_state.py",
  "packages\stinky-core\src\stinky_core\events\base.py",
  "packages\stinky-core\tests\test_identity.py",
  "packages\stinky-core\tests\test_memory.py",
  "packages\stinky-core\tests\test_intelligence.py",
  "packages\stinky-core\tests\test_book.py",
  "packages\stinky-core\tests\test_recognition.py",
  "packages\stinky-core\tests\test_evidence_engine.py",
  "packages\stinky-core\tests\test_observe.py",
  "packages\stinky-core\tests\test_quality_state.py",
  "packages\stinky-core\tests\test_hardening.py",
  "packages\stinky-core\tests\test_live_pipeline.py",
  "packages\stinky-core\tests\test_eligibility_matrix.py",
  "services\sentinel\src\sentinel\durable.py",
  "services\sentinel\src\sentinel\volume.py",
  "services\sentinel\src\sentinel\qualify.py",
  "services\sentinel\src\sentinel\cli.py",
  "services\sentinel\src\sentinel\config.py",
  "services\sentinel\migrations\006_intelligence_memory.sql",
  "services\sentinel\migrations\007_memory_enrich.sql",
  "services\sentinel\migrations\008_market_observations.sql",
  "services\sentinel\migrations\009_observations.sql",
  "services\sentinel\migrations\010_quality_states.sql",
  "services\api\src\stinky_api\main.py",
  "services\api\src\stinky_api\queries.py",
  "services\sentinel\tests\test_qualify_fees_gate.py",
  "services\discord-bot\src\discord_bot\alerter.py",
  "services\discord-bot\src\discord_bot\policy.py",
  "services\discord-bot\tests\test_policy.py",
  "apps\web\src\lib\api\client.ts",
  "apps\web\src\components\layout\Sidebar.tsx",
  "apps\web\src\components\layout\AppShell.tsx",
  "apps\web\src\components\command-center\CommandCenter.tsx",
  "apps\web\src\app\investigations\page.tsx",
  "apps\web\src\app\observations\page.tsx",
  "apps\web\src\app\recipes\page.tsx",
  "apps\web\src\app\unknown\page.tsx",
  "apps\web\src\app\health\page.tsx",
  "apps\web\src\app\dips\page.tsx",
  "apps\web\src\app\creators\[address]\page.tsx",
  "apps\web\src\app\tokens\[mint]\page.tsx",
  "docs\adr\ADR-014-remember.md",
  "docs\adr\ADR-015-intelligence-book.md",
  "docs\adr\ADR-016-recognition.md",
  "docs\adr\ADR-017-evidence.md",
  "docs\adr\ADR-018-observe.md",
  "docs\adr\ADR-019-genesis-boundary.md",
  "docs\adr\ADR-020-quality-state.md",
  "docs\adr\ADR-021-live-validation.md",
  "docs\GENESIS.md",
  "docker-compose.yml",
  "README.md",
  "stop-stinky.ps1",
  ".env.example",
  "scripts\diagnose-stinky.ps1"
)

foreach ($rel in $paths) {
  $from = Join-Path $src $rel
  $to = Join-Path $dst $rel
  if (-not (Test-Path -LiteralPath $from)) { throw "Missing overlay file: $rel" }
  $parent = Split-Path -Parent $to
  if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
  Copy-Item -Force -LiteralPath $from -Destination $to
  Write-Host "applied $rel"
}

Write-Host ""
Write-Host "Applied intel-v1.10.0-live-validation. Restart:"
Write-Host "  powershell -File D:\Work\Project-Genesis\stop-stinky.ps1"
Write-Host "  .venv\Scripts\python.exe D:\Work\Project-Genesis\start_genesis.py --skip-sync"
Write-Host "Verify: Gate 1 unchanged at `$150k. After Gate 1, ticks continue even if volume dumps."
Write-Host "Restart: open investigations inside T+1800 resume. pumpfun bonding is not migrated."
Write-Host "Quality: POST /v1/book/quality  Dips: POST /v1/book/dips"
Write-Host "Discord: state-change only. Same state silent. Not a trade signal."
