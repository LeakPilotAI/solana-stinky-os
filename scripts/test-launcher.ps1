# Windows-side launcher contract checks. Safe to run without starting the stack.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $root "start-stinky.ps1"))) { $root = $PSScriptRoot }

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
Assert-Contains "Start-Stinky-OS.cmd" "ExecutionPolicy Bypass" "execution policy handling"
Assert-Contains "Start-Stinky-OS.cmd" "pause" "window does not silently close"
Assert-Contains "Start-Stinky-OS.cmd" "WindowsPowerShell\v1.0\powershell.exe" "absolute PowerShell"
Assert-Contains "start-stinky.ps1" "ALREADY RUNNING" "duplicate-launch protection"
Assert-Contains "start-stinky.ps1" "startup.log" "predictable startup log"
Assert-Contains "start-stinky.ps1" "cmd START" "break away from Explorer job so services survive"
Assert-Contains "stop-stinky.ps1" "Test-GenesisOwned" "stop is ownership-gated"
Assert-NotContains "stop-stinky.ps1" "Get-Process python" "must not kill generic python"
Assert-NotContains "stop-stinky.ps1" "Get-Process node" "must not kill generic node"
Assert-Contains "install-desktop-shortcut.ps1" "System32\cmd.exe" "shortcut uses absolute cmd.exe"
Assert-Contains "install-desktop-shortcut.ps1" "/d /k" "shortcut keeps the window open"

Write-Host "syntax parse" -ForegroundColor Cyan
foreach ($f in @("start-stinky.ps1", "stop-stinky.ps1", "install-desktop-shortcut.ps1")) {
  $errs = $null
  $null = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $root $f), [ref]$null, [ref]$errs)
  if ($errs) { throw "$f parse: $($errs | Out-String)" }
  Write-Host "  ok parse $f" -ForegroundColor Green
}
Write-Host "PASS" -ForegroundColor Green
exit 0
