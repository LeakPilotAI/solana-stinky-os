# Desktop start does not use this file.
# Start-Stinky-OS.cmd runs start_genesis.py so Windows Defender AMSI cannot block start.
param(
  [switch]$SkipSync,
  [switch]$Sync,
  [switch]$Restart,
  [switch]$SkipInstall
)
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $py)) { $py = "python" }
$a = @()
if ($SkipSync) { $a += "--skip-sync" }
if ($Sync) { $a += "--sync" }
if ($Restart) { $a += "--restart" }
if ($SkipInstall) { $a += "--skip-install" }
& $py (Join-Path $PSScriptRoot "start_genesis.py") @a
exit $LASTEXITCODE
