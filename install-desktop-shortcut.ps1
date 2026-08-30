# Recreate desktop shortcuts: Genesis + Stop Genesis
$ErrorActionPreference = "Continue"
$root = "D:\Work\Project-Genesis"
$desktop = [Environment]::GetFolderPath("Desktop")
$desktops = @($desktop)
$od = Join-Path $env:USERPROFILE "OneDrive\Desktop"
if (Test-Path $od) { $desktops += $od }

Unblock-File "$root\start-stinky.ps1" -ErrorAction SilentlyContinue
Unblock-File "$root\stop-stinky.ps1" -ErrorAction SilentlyContinue
Unblock-File "$root\Start-Stinky-OS.cmd" -ErrorAction SilentlyContinue
Unblock-File "$root\Stop-Stinky-OS.cmd" -ErrorAction SilentlyContinue
Unblock-File "$root\APPLY-refresh.ps1" -ErrorAction SilentlyContinue

$ws = New-Object -ComObject WScript.Shell
foreach ($desk in $desktops | Select-Object -Unique) {
  foreach ($pair in @(
      @{ Name = "Genesis.lnk"; Target = "$root\Start-Stinky-OS.cmd"; Desc = "Start Genesis operator box" },
      @{ Name = "Stinky OS.lnk"; Target = "$root\Start-Stinky-OS.cmd"; Desc = "Start Genesis / Stinky OS" },
      @{ Name = "Stop Genesis.lnk"; Target = "$root\Stop-Stinky-OS.cmd"; Desc = "Stop Genesis apps + containers" },
      @{ Name = "Refresh Genesis.lnk"; Target = "$root\Refresh-Genesis.cmd"; Desc = "Overwrite Project-Genesis from GitHub, keep .env" }
    )) {
    $lnk = Join-Path $desk $pair.Name
    Remove-Item $lnk -Force -ErrorAction SilentlyContinue
    $sc = $ws.CreateShortcut($lnk)
    $sc.TargetPath = $pair.Target
    $sc.WorkingDirectory = $root
    $sc.WindowStyle = 1
    $sc.Description = $pair.Desc
    $sc.Save()
    Write-Host "Created: $lnk" -ForegroundColor Green
  }
}
Write-Host "Double-click  Genesis  on the desktop. Stop with  Stop Genesis." -ForegroundColor Cyan
