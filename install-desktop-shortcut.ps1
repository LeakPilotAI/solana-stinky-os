$target = "D:\Work\Project-Genesis\Start-Stinky-OS.cmd"
$desktop = [Environment]::GetFolderPath("Desktop")
$lnkPath = Join-Path $desktop "Stinky OS.lnk"
$w = New-Object -ComObject WScript.Shell
$s = $w.CreateShortcut($lnkPath)
$s.TargetPath = $target
$s.WorkingDirectory = "D:\Work\Project-Genesis"
$s.WindowStyle = 1
$s.Description = "Start Stinky OS (Docker + apps)"
$s.Save()
Write-Host "Desktop shortcut: $lnkPath -> $target" -ForegroundColor Green
