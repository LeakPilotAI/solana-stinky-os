# Optional read-only window. Closing it never stops Genesis or Docker.
param([Alias("Json")][switch]$Check)
$ErrorActionPreference = "Stop"

function Get-GenesisPanelSnapshot {
    $status = & (Join-Path $PSScriptRoot "Genesis-Background-Status.ps1") -Json | ConvertFrom-Json
    $services = @($status.services_expected | ForEach-Object {
        $name = $_
        $matches = @($status.processes | Where-Object {
            $_.service -ceq $name -and $_.classification -in @("SUPERVISOR_CANDIDATE", "SUPERVISOR_VERIFIED")
        })
        $label = if ($matches.Count -gt 1) { "Conflicting supervisors" }
            elseif ($matches.Count -eq 1 -and $matches[0].classification -ceq "SUPERVISOR_VERIFIED") { "Supervisor observed" }
            elseif ($matches.Count -eq 1) { "Ownership check needed" }
            elseif ($status.inventory_error) { "Unavailable" }
            else { "Not observed" }
        [pscustomobject]@{ service = $name; status = $label }
    })
    [pscustomobject]@{
        title = "Genesis Background Status"
        checked_at = [string]$status.timestamp_utc
        message = if ($status.state -ceq "ERROR") { "Some checks are unavailable. No services were changed." }
            else { "Read-only snapshot. Supervisor evidence does not prove collection freshness." }
        services = $services
        dependencies = @($status.docker | ForEach-Object {
            [pscustomobject]@{ dependency = $_.name; state = $_.state; ownership = $_.ownership }
        })
        actions = [pscustomobject]@{ start_enabled = $false; stop_enabled = $false;
            restart_enabled = $false; gaming_enabled = $false }
        action_notice = "Startup, shutdown and gaming controls are blocked pending safety certification."
        authority = "Paper-only. No live trading authority."
    }
}

if ($Check) { Get-GenesisPanelSnapshot | ConvertTo-Json -Depth 8; return }

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
$form = New-Object Windows.Forms.Form
$form.Text = "Genesis Background Status"
$form.Size = New-Object Drawing.Size(920, 680)
$form.MinimumSize = New-Object Drawing.Size(740, 560)
$form.StartPosition = "CenterScreen"
$form.Font = New-Object Drawing.Font("Segoe UI", 10)
$layout = New-Object Windows.Forms.TableLayoutPanel
$layout.Dock = "Fill"; $layout.ColumnCount = 1; $layout.RowCount = 6
$layout.Padding = New-Object Windows.Forms.Padding(16)
$layout.RowStyles.Add((New-Object Windows.Forms.RowStyle("Absolute", 62)))
$layout.RowStyles.Add((New-Object Windows.Forms.RowStyle("Percent", 55)))
$layout.RowStyles.Add((New-Object Windows.Forms.RowStyle("Percent", 45)))
$layout.RowStyles.Add((New-Object Windows.Forms.RowStyle("Absolute", 48)))
$layout.RowStyles.Add((New-Object Windows.Forms.RowStyle("Absolute", 56)))
$layout.RowStyles.Add((New-Object Windows.Forms.RowStyle("Absolute", 32)))
$heading = New-Object Windows.Forms.Label
$heading.Dock = "Fill"; $heading.AutoSize = $true; $heading.AccessibleName = "Current status"
$layout.Controls.Add($heading, 0, 0)
function New-StatusGrid($name) {
    $grid = New-Object Windows.Forms.DataGridView
    $grid.Dock = "Fill"; $grid.ReadOnly = $true; $grid.AllowUserToAddRows = $false
    $grid.AllowUserToDeleteRows = $false; $grid.AutoSizeColumnsMode = "Fill"
    $grid.RowHeadersVisible = $false; $grid.AccessibleName = $name
    return $grid
}
$serviceGrid = New-StatusGrid "Genesis supervisors"
$dependencyGrid = New-StatusGrid "Genesis dependencies"
$layout.Controls.Add($serviceGrid, 0, 1); $layout.Controls.Add($dependencyGrid, 0, 2)
$buttons = New-Object Windows.Forms.FlowLayoutPanel
$buttons.Dock = "Fill"
$refresh = New-Object Windows.Forms.Button
$refresh.Text = "Refresh status"; $refresh.AutoSize = $true
$buttons.Controls.Add($refresh)
foreach ($text in @("Start", "Stop", "Restart", "Gaming mode")) {
    $button = New-Object Windows.Forms.Button
    $button.Text = $text; $button.Enabled = $false; $button.AutoSize = $true
    $buttons.Controls.Add($button)
}
$layout.Controls.Add($buttons, 0, 3)
$notice = New-Object Windows.Forms.Label
$notice.Dock = "Fill"; $notice.AutoSize = $true
$notice.Text = "Startup, shutdown and gaming controls are blocked pending safety certification."
$layout.Controls.Add($notice, 0, 4)
$authority = New-Object Windows.Forms.Label
$authority.Dock = "Fill"; $authority.Text = "Paper-only. No live trading authority."
$layout.Controls.Add($authority, 0, 5); $form.Controls.Add($layout)
$refresh.Add_Click({
    $refresh.Enabled = $false
    try {
        $snapshot = Get-GenesisPanelSnapshot
        $heading.Text = $snapshot.message + "`r`nChecked: " + $snapshot.checked_at
        $serviceGrid.DataSource = [System.Collections.ArrayList]@($snapshot.services)
        $dependencyGrid.DataSource = [System.Collections.ArrayList]@($snapshot.dependencies)
    }
    catch { $heading.Text = "Status is unavailable. No services were changed." }
    finally { $refresh.Enabled = $true }
})
$form.Add_Shown({ $refresh.PerformClick() })
try { [void]$form.ShowDialog() } finally { $form.Dispose() }
