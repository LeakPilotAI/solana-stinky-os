# Windows-side launcher contract checks. Safe to run without starting the stack.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $root "start_genesis.py"))) { $root = $PSScriptRoot }

function Assert-Contains([string]$Path, [string]$Needle, [string]$Why) {
  $t = Get-Content -LiteralPath (Join-Path $root $Path) -Raw
  if ($t -notlike "*$Needle*") {
    throw "FAIL $Path : expected '$Needle' ($Why)"
  }
  Write-Host "  ok $Path :: $Why" -ForegroundColor Green
}

function Assert-NotContains([string]$Path, [string]$Needle, [string]$Why) {
  $t = Get-Content -LiteralPath (Join-Path $root $Path) -Raw
  if ($t -like "*$Needle*") {
    throw "FAIL $Path : must not contain '$Needle' ($Why)"
  }
  Write-Host "  ok $Path :: $Why" -ForegroundColor Green
}

Write-Host "GENESIS launcher contract (Windows)" -ForegroundColor Cyan
Assert-Contains "Start-Stinky-OS.cmd" "%~dp0" "script-relative project root"
Assert-Contains "Start-Stinky-OS.cmd" "start_genesis.py" "desktop start is Python, not PowerShell"
Assert-Contains "Start-Stinky-OS.cmd" "pause" "window does not silently close"
Assert-NotContains "Start-Stinky-OS.cmd" "start-stinky.ps1" "must not load the AMSI-blocked ps1"
Assert-Contains "start_genesis.py" "ALREADY RUNNING" "duplicate-launch protection"
Assert-Contains "start_genesis.py" "startup.log" "predictable startup log"
Assert-Contains "start_genesis.py" "start-genesis-svc.cmd" "break away from Explorer job so services survive"
Assert-Contains "stop-stinky.ps1" "Test-GenesisOwned" "stop is ownership-gated"
Assert-NotContains "stop-stinky.ps1" "Get-Process python" "must not kill generic python"
Assert-NotContains "stop-stinky.ps1" "Get-Process node" "must not kill generic node"
Assert-Contains "install-desktop-shortcut.ps1" "System32\cmd.exe" "shortcut uses absolute cmd.exe"
Assert-Contains "install-desktop-shortcut.ps1" "/d /k" "shortcut keeps the window open"
Assert-Contains "start_genesis.py" "restore_search_path" "Explorer PATH restore"
Assert-Contains "scripts/start-genesis-svc.cmd" "run_genesis_service.py" "allowlisted python runner"
Assert-Contains "APPLY-launcher.ps1" "install-desktop-shortcut.ps1" "VS Code apply remakes the shortcut"
Assert-Contains "APPLY-launcher.ps1" "[switch]$Start" "apply does not start the stack unless asked"

Write-Host "syntax parse" -ForegroundColor Cyan
foreach ($f in @("stop-stinky.ps1", "install-desktop-shortcut.ps1", "APPLY-launcher.ps1", "APPLY-refresh.ps1")) {
  $errs = $null
  $null = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $root $f), [ref]$null, [ref]$errs)
  if ($errs) { throw "$f parse: $($errs | Out-String)" }
  Write-Host "  ok parse $f" -ForegroundColor Green
}
Write-Host "PASS" -ForegroundColor Green
exit 0
