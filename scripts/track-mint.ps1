# Track a missed pump CA through Stinky OS (volume + collector)
param(
  [Parameter(Mandatory = $true)][string]$Mint,
  [string]$Note = "manual",
  [string]$Api = "http://127.0.0.1:8010"
)
$Mint = $Mint.Trim()
if (-not $Mint.ToLower().EndsWith("pump")) {
  Write-Host "Mint must end with pump" -ForegroundColor Red
  exit 1
}
$body = @{ mint = $Mint; note = $Note } | ConvertTo-Json
try {
  $r = Invoke-RestMethod -Method POST -Uri "$Api/v1/track" -ContentType "application/json" -Body $body
  $r | ConvertTo-Json -Depth 5
} catch {
  Write-Host "API track failed: $_" -ForegroundColor Red
  exit 1
}
