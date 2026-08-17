# Recreate desktop shortcuts (Start + Stop)
$ErrorActionPreference = "Continue"
$root = "D:\Work\Project-Genesis"
$desktop = [Environment]::GetFolderPath("Desktop")
# also OneDrive desktop if present
$desktops = @($desktop)
$od = Join-Path $env:USERPROFILE "OneDrive\Desktop"
if (Test-Path $od) { $desktops += $od }

Unblock-File "$root\start-stinky.ps1" -ErrorAction SilentlyContinue
Unblock-File "$root\stop-stinky.ps1" -ErrorAction SilentlyContinue

$ws = New-Object -ComObject WScript.Shell
foreach ($desk in $desktops | Select-Object -Unique) {
    # Start
    $lnk = Join-Path $desk "Stinky OS.lnk"
    Remove-Item $lnk -Force -ErrorAction SilentlyContinue
    $sc = $ws.CreateShortcut($lnk)
    $sc.TargetPath = "powershell.exe"
    $sc.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$root\start-stinky.ps1`""
    $sc.WorkingDirectory = $root
    $sc.WindowStyle = 1
    $sc.Description = "Start Stinky OS - close window to full stop"
    $sc.Save()
    Write-Host "Created: $lnk" -ForegroundColor Green

    # Stop
    $lnk2 = Join-Path $desk "Stop Stinky OS.lnk"
    Remove-Item $lnk2 -Force -ErrorAction SilentlyContinue
    $sc2 = $ws.CreateShortcut($lnk2)
    $sc2.TargetPath = "powershell.exe"
    $sc2.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$root\stop-stinky.ps1`""
    $sc2.WorkingDirectory = $root
    $sc2.WindowStyle = 1
    $sc2.Description = "Stop Stinky OS apps + Genesis containers"
    $sc2.Save()
    Write-Host "Created: $lnk2" -ForegroundColor Green
}
Write-Host "Done. Double-click Stinky OS to start. Close that window to stop everything." -ForegroundColor Cyan
