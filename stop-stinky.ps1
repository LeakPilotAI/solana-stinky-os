# Compatibility entry point: application-only, no Docker commands or PID-file trust.
$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { Write-Error 'Existing Genesis environment required'; exit 1 }
Set-Location -LiteralPath $PSScriptRoot
& $python -m scripts.safe_genesis_stop
exit $LASTEXITCODE
