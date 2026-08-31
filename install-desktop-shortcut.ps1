# Recreate desktop + Start Menu shortcuts for Genesis.
# Only two icons: Genesis (start) and Stop Genesis.
# Shortcut target is cmd.exe with absolute paths. No Explorer cwd, no relative paths.
$ErrorActionPreference = "Continue"

function Get-ScriptRoot {
  if ($PSScriptRoot) { return $PSScriptRoot }
  if ($MyInvocation.MyCommand.Path) { return (Split-Path -Parent $MyInvocation.MyCommand.Path) }
  return (Get-Location).Path
}

$root = Get-ScriptRoot
$cmdExe = Join-Path $env:SystemRoot "System32\cmd.exe"
$startCmd = Join-Path $root "Start-Stinky-OS.cmd"
$stopCmd = Join-Path $root "Stop-Stinky-OS.cmd"

foreach ($f in @(
  (Join-Path $root "stop-stinky.ps1"),
  $startCmd,
  $stopCmd,
  (Join-Path $root "Start-Genesis.cmd"),
  (Join-Path $root "Stop-Genesis.cmd"),
  (Join-Path $root "APPLY-refresh.ps1"),
  (Join-Path $root "APPLY-launcher.ps1"),
  (Join-Path $root "start_genesis.py"),
  (Join-Path $root "scripts\run_genesis_service.py"),
  (Join-Path $root "scripts\start-genesis-svc.cmd")
)) {
  if (Test-Path -LiteralPath $f) { Unblock-File -LiteralPath $f -ErrorAction SilentlyContinue }
}

if (-not (Test-Path -LiteralPath $startCmd)) {
  Write-Host "MISSING launcher: $startCmd" -ForegroundColor Red
  exit 1
}
if (-not (Test-Path -LiteralPath (Join-Path $root "start_genesis.py"))) {
  Write-Host "MISSING start_genesis.py - pull origin/main" -ForegroundColor Red
  exit 1
}
if (-not (Test-Path -LiteralPath $cmdExe)) {
  Write-Host "MISSING cmd.exe: $cmdExe" -ForegroundColor Red
  exit 1
}

$desktop = [Environment]::GetFolderPath("Desktop")
$desktops = @($desktop)
$od = Join-Path $env:USERPROFILE "OneDrive\Desktop"
if (Test-Path $od) { $desktops += $od }
$userDesk = Join-Path $env:USERPROFILE "Desktop"
if (Test-Path $userDesk) { $desktops += $userDesk }
$pub = [Environment]::GetFolderPath("CommonDesktopDirectory")
if ($pub -and (Test-Path $pub)) {
  $canPub = $false
  try {
    $probe = Join-Path $pub ("genesis-write-probe-" + [guid]::NewGuid().ToString("N") + ".tmp")
    [System.IO.File]::WriteAllText($probe, "ok")
    Remove-Item -LiteralPath $probe -Force -ErrorAction SilentlyContinue
    $canPub = $true
  } catch { $canPub = $false }
  if ($canPub) { $desktops += $pub }
  else { Write-Host "  skip $pub (no permission)" -ForegroundColor DarkGray }
}
$startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
if (Test-Path $startMenu) { $desktops += $startMenu }
$desktops += $root

$stale = @(
  "Stinky OS.lnk",
  "Apply Genesis Launcher.lnk",
  "Refresh Genesis.lnk",
  "Apply Genesis.lnk",
  "Start Genesis.lnk",
  "Start Stinky OS.lnk"
)

$ws = New-Object -ComObject WScript.Shell
$pairs = @(
  @{ Name = "Genesis.lnk"; Target = $startCmd; Desc = "Start Genesis operator box" },
  @{ Name = "Stop Genesis.lnk"; Target = $stopCmd; Desc = "Stop Genesis-owned apps + containers" }
)

$ok = 0
foreach ($desk in ($desktops | Select-Object -Unique)) {
  if (-not $desk) { continue }
  if (-not (Test-Path -LiteralPath $desk)) { continue }
  foreach ($name in $stale) {
    $junk = Join-Path $desk $name
    if (Test-Path -LiteralPath $junk) {
      Remove-Item -LiteralPath $junk -Force -ErrorAction SilentlyContinue
      Write-Host "  removed leftover $junk" -ForegroundColor DarkGray
    }
  }
  foreach ($pair in $pairs) {
    if (-not (Test-Path -LiteralPath $pair.Target)) { continue }
    $lnk = Join-Path $desk $pair.Name
    Remove-Item $lnk -Force -ErrorAction SilentlyContinue
    $sc = $ws.CreateShortcut($lnk)
    $sc.TargetPath = $cmdExe
    $sc.Arguments = "/d /k `"$($pair.Target)`""
    $sc.WorkingDirectory = $root
    $sc.WindowStyle = 1
    $sc.Description = $pair.Desc
    try { $sc.Save() } catch {
      Write-Host "  skip $lnk (no permission)" -ForegroundColor DarkGray
      continue
    }
    $check = $ws.CreateShortcut($lnk)
    if ($check.TargetPath -notmatch "cmd\.exe") {
      Write-Host "VERIFY FAIL $lnk still points at $($check.TargetPath)" -ForegroundColor Red
      continue
    }
    Write-Host "Created: $lnk" -ForegroundColor Green
    Write-Host "  target  $($check.TargetPath)" -ForegroundColor DarkGray
    Write-Host "  args    $($check.Arguments)" -ForegroundColor DarkGray
    Write-Host "  cwd     $($check.WorkingDirectory)" -ForegroundColor DarkGray
    $ok = $ok + 1
  }
}

if ($ok -lt 1) {
  Write-Host "NO shortcuts written." -ForegroundColor Red
  exit 1
}
Write-Host "Double-click  Genesis  on the desktop. Window stays open. Services stay up if you close it." -ForegroundColor Cyan
Write-Host "Stop with  Stop Genesis." -ForegroundColor Cyan
exit 0
