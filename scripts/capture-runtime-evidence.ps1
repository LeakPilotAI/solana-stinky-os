param(
  [int]$DurationMinutes = 0
)
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$logs = Join-Path $root "logs"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$out = Join-Path $logs ("runtime-evidence-" + $stamp + ".txt")
$script:SnapshotFailed = $false
New-Item -ItemType Directory -Force -Path $logs | Out-Null

function Write-Evidence([string]$Text) {
  $Text | Tee-Object -FilePath $out -Append
}
function Capture-Url([string]$Label, [string]$Url) {
  Write-Evidence ("=== " + $Label + " ===")
  try {
    $r = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 5
    Write-Evidence ("HTTP " + [int]$r.StatusCode)
    Write-Evidence $r.Content
    if ($Label -eq "SUPERVISOR EVIDENCE" -and $r.Content -match '"status"\s*:\s*"FAILED"') { $script:SnapshotFailed = $true }
  } catch {
    Write-Evidence ("UNAVAILABLE " + $_.Exception.Message)
    $script:SnapshotFailed = $true
  }
}
function Snapshot {
  Write-Evidence ("\n===== SNAPSHOT " + (Get-Date).ToUniversalTime().ToString("o") + " =====")
  Capture-Url "EVENT LOG HEALTH" "http://127.0.0.1:8002/health"
  Capture-Url "API HEALTH" "http://127.0.0.1:8010/health"
  Capture-Url "SUPERVISOR EVIDENCE" "http://127.0.0.1:8010/v1/system/runtime-supervisors"
  Capture-Url "WEB OPERATOR" "http://127.0.0.1:3000/operator"
  Write-Evidence "=== GENESIS PID FILE ==="
  $pidFile = Join-Path $logs "stinky-pids.txt"
  if (Test-Path $pidFile) { Get-Content $pidFile | Tee-Object -FilePath $out -Append } else { Write-Evidence "MISSING" }
  Write-Evidence "=== GENESIS-OWNED PROCESS COMMAND LINES ==="
  Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and ($_.CommandLine -like "*run_genesis_service.py*" -or $_.CommandLine -like "*start_genesis.py*" -or $_.CommandLine -like "*start_paper_runtime.py*")
  } | Select-Object ProcessId, ParentProcessId, Name, CommandLine | Format-List | Out-String | Tee-Object -FilePath $out -Append
  Write-Evidence "=== PER-SERVICE RUNTIME STATE ==="
  Get-ChildItem $logs -Filter "runtime-state-*.json" -ErrorAction SilentlyContinue | Sort-Object Name | ForEach-Object {
    Write-Evidence ("--- " + $_.Name + " ---")
    Get-Content $_.FullName -Raw | Tee-Object -FilePath $out -Append
  }
  Write-Evidence "=== RECENT SERVICE LOG TAILS ==="
  $names = @("event-log","api","sentinel","discord","collector","entities","web","maintain","paper-intake-producer","paper-runtime","startup")
  foreach ($name in $names) {
    $p = Join-Path $logs ($name + ".log")
    if (Test-Path $p) {
      Write-Evidence ("--- " + $name + ".log (last 80 lines) ---")
      Get-Content $p -Tail 80 -ErrorAction SilentlyContinue | Tee-Object -FilePath $out -Append
    }
  }
}
Snapshot
if ($DurationMinutes -gt 0) {
  $deadline = (Get-Date).AddMinutes($DurationMinutes)
  while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 60
    Snapshot
  }
}
Write-Evidence ("\nEVIDENCE_FILE=" + $out)
if ($script:SnapshotFailed) {
  Write-Host "Runtime evidence captured with failures: $out" -ForegroundColor Red
  exit 1
}
Write-Host "Runtime evidence captured cleanly: $out" -ForegroundColor Green
exit 0
