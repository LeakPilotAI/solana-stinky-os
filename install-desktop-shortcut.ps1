# Recreate desktop + Start Menu shortcuts for Genesis.
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
$refreshCmd = Join-Path $root "Refresh-Genesis.cmd"
$applyCmd = Join-Path $root "APPLY-launcher.cmd"

foreach ($f in @(
  (Join-Path $root "start-stinky.ps1"),
  (Join-Path $root "stop-stinky.ps1"),
  $startCmd,
  $stopCmd,
  (Join-Path $root "Start-Genesis.cmd"),
  (Join-Path $root "Stop-Genesis.cmd"),
  $refreshCmd,
  $applyCmd,
  (Join-Path $root "APPLY-refresh.ps1"),
  (Join-Path $root "APPLY-launcher.ps1")
)) {
  if (Test-Path -LiteralPath $f) { Unblock-File -LiteralPath $f -ErrorAction SilentlyContinue }
}

if (-not (Test-Path -LiteralPath $startCmd)) {
  Write-Host "MISSING launcher: $startCmd" -ForegroundColor Red
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
if ($pub -and (Test-Path $pub)) { $desktops += $pub }
$startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
if (Test-Path $startMenu) { $desktops += $startMenu }
$desktops += $root

$ws = New-Object -ComObject WScript.Shell
$pairs = @(
  @{ Name = "Genesis.lnk"; Target = $startCmd; Desc = "Start Genesis operator box" },
  @{ Name = "Stinky OS.lnk"; Target = $startCmd; Desc = "Start Genesis / Stinky OS" },
  @{ Name = "Stop Genesis.lnk"; Target = $stopCmd; Desc = "Stop Genesis-owned apps + containers" }
)
if (Test-Path -LiteralPath $refreshCmd) {
  $pairs += @{ Name = "Refresh Genesis.lnk"; Target = $refreshCmd; Desc = "Overwrite Project-Genesis from GitHub, keep .env" }
}
if (Test-Path -LiteralPath $applyCmd) {
  $pairs += @{ Name = "Apply Genesis Launcher.lnk"; Target = $applyCmd; Desc = "Pull main and remake Genesis.lnk" }
}

$ok = 0
foreach ($desk in ($desktops | Select-Object -Unique)) {
  if (-not $desk) { continue }
  if (-not (Test-Path -LiteralPath $desk)) { continue }
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
      Write-Host "FAILED save $lnk  $($_.Exception.Message)" -ForegroundColor Red
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
