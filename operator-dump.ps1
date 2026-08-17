# operator-dump.ps1 - snapshot logs + DB decisions for analysis
$ErrorActionPreference = "Continue"
$root = "D:\Work\Project-Genesis"
Set-Location $root
$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$out = Join-Path $root "dumps\operator-$ts"
New-Item -ItemType Directory -Force -Path $out | Out-Null
New-Item -ItemType Directory -Force -Path "$out\logs" | Out-Null

Write-Host "Operator dump -> $out" -ForegroundColor Cyan

# 1) Service logs (last ~2000 lines each)
$logNames = @("sentinel","api","event-log","collector","discord","entities","maintain","web")
foreach ($n in $logNames) {
  $src = Join-Path $root "logs\$n.log"
  $dst = Join-Path $out "logs\$n.log"
  if (Test-Path $src) {
    Get-Content $src -Tail 2000 -EA SilentlyContinue | Set-Content $dst -Encoding utf8
    Write-Host "  log $n" -ForegroundColor Green
  } else {
    Write-Host "  skip log $n (missing)" -ForegroundColor Yellow
  }
}

# 2) Health snapshot
$health = @{}
foreach ($url in @(
  "http://127.0.0.1:8010/health",
  "http://127.0.0.1:8002/health"
)) {
  try {
    $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5
    $health[$url] = $r.Content
  } catch {
    $health[$url] = "FAIL: $($_.Exception.Message)"
  }
}
$health | ConvertTo-Json | Set-Content "$out\health.json" -Encoding utf8

# 3) PIDs
if (Test-Path "logs\stinky-pids.txt") {
  Copy-Item "logs\stinky-pids.txt" "$out\stinky-pids.txt"
}

# 4) DB decision queries via docker exec psql
$pg = "stinky-postgres"
$dbUser = "stinky"
$dbName = "stinky"
# Try common env defaults if needed
function Invoke-Sql([string]$Sql, [string]$FileName) {
  $tmpSql = Join-Path $env:TEMP "stinky-dump-$FileName.sql"
  Set-Content -Path $tmpSql -Value $Sql -Encoding ascii
  $raw = docker exec -i $pg psql -U $dbUser -d $dbName -v ON_ERROR_STOP=0 -A -F "," -c $Sql 2>&1
  $raw | Set-Content (Join-Path $out $FileName) -Encoding utf8
  Write-Host "  sql $FileName ($($raw.Count) lines)" -ForegroundColor Green
}

# Filter evaluations (accept/reject with reasons + fees)
Invoke-Sql @"
SELECT id, mint, filter_version, accepted, evaluated_at,
       protocol, global_fees_sol, global_fees_source, global_fees_verified,
       liquidity_usd, volume_usd, market_cap_usd,
       rejection_reason, failed_filters::text, passed_filters::text
FROM filter_evaluations
ORDER BY evaluated_at DESC
LIMIT 200;
"@ "filter_evaluations_recent.csv"

Invoke-Sql @"
SELECT accepted, COUNT(*)::int AS n
FROM filter_evaluations
WHERE evaluated_at > NOW() - INTERVAL '24 hours'
GROUP BY accepted
ORDER BY accepted;
"@ "filter_eval_24h_counts.csv"

Invoke-Sql @"
SELECT rejection_reason, COUNT(*)::int AS n
FROM filter_evaluations
WHERE evaluated_at > NOW() - INTERVAL '24 hours'
  AND accepted = false
GROUP BY rejection_reason
ORDER BY n DESC
LIMIT 50;
"@ "filter_reject_reasons_24h.csv"

# Recent migrations + tracks
Invoke-Sql @"
SELECT mint, pool, creator, migration_at, status, buyers_captured, trades_observed
FROM migration_tracks
ORDER BY migration_at DESC NULLS LAST
LIMIT 100;
"@ "migration_tracks_recent.csv"

# Alert candidates from events
Invoke-Sql @"
SELECT event_id::text, event_type, subject_id, occurred_at, payload::text
FROM events
WHERE event_type = 'alert.candidate'
ORDER BY occurred_at DESC
LIMIT 100;
"@ "alert_candidates_recent.csv"

# Alert log if present
Invoke-Sql @"
SELECT *
FROM alert_log
ORDER BY created_at DESC NULLS LAST
LIMIT 100;
"@ "alert_log_recent.csv"

# Score snapshots
Invoke-Sql @"
SELECT mint, score, confidence, captured_at, payload::text
FROM score_snapshots
ORDER BY captured_at DESC NULLS LAST
LIMIT 100;
"@ "score_snapshots_recent.csv"

# Env gate knobs (no secrets - strip keys)
if (Test-Path ".env") {
  Get-Content ".env" |
    Where-Object { $_ -match "^(STINKY_|FILTER_|ALERT_|MIN_)" -and $_ -notmatch "KEY|TOKEN|SECRET|PASSWORD|PRIVATE" } |
    Set-Content "$out\env_gates.txt" -Encoding utf8
}

# README
@"
STINKY OS operator dump - $ts

What to send for analysis:
1. This whole folder, OR zip it:
   Compress-Archive -Path '$out' -DestinationPath '$out.zip'

Priority files:
- filter_evaluations_recent.csv  = every accept/reject + fees + reasons
- filter_reject_reasons_24h.csv  = why garbage was blocked
- alert_candidates_recent.csv    = what was allowed through to alert path
- score_snapshots_recent.csv     = scores attached to mints
- logs/sentinel.log              = live migration/filter path
- logs/api.log                   = UI query errors/timeouts
- env_gates.txt                  = active fee/volume thresholds (no secrets)

If filter_evaluations_* files say relation does not exist, run migration 003_filter_evaluations.sql.
"@ | Set-Content "$out\README.txt" -Encoding utf8

Write-Host ""
Write-Host "DONE: $out" -ForegroundColor Green
Write-Host "Zip it:" -ForegroundColor Cyan
Write-Host "  Compress-Archive -Path `"$out`" -DestinationPath `"$out.zip`" -Force"
