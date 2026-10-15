param(
    [Parameter(Mandatory = $true)]
    [ValidateSet(
        "event-log", "api", "sentinel", "collector",
        "entities", "web", "maintain"
    )]
    [string]$Service,

    [Parameter(Mandatory = $true)]
    [int]$ProcessId,

    [Parameter(Mandatory = $true)]
    [string]$ProcessCreated
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$heartbeatPath = Join-Path $root "logs\runtime-state-$Service.json"

$result = [ordered]@{
    service = $Service
    pid = $ProcessId
    verified = $false
    reason = "UNVERIFIED"
}

try {
    if (-not (Test-Path -LiteralPath $heartbeatPath -PathType Leaf)) {
        throw "HEARTBEAT_MISSING"
    }

    # Read at most 16 KiB plus one byte, including if the file grows.
    $stream = [System.IO.File]::Open(
        $heartbeatPath,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::ReadWrite
    )

    try {
        $buffer = New-Object byte[] 16385
        $total = 0

        while ($total -lt $buffer.Length) {
            $read = $stream.Read(
                $buffer,
                $total,
                $buffer.Length - $total
            )

            if ($read -eq 0) {
                break
            }

            $total += $read
        }

        if ($total -gt 16384) {
            throw "HEARTBEAT_TOO_LARGE"
        }

        # Allow an optional UTF-8 BOM while retaining the full byte limit.
        $offset = 0

        if (
            $total -ge 3 -and
            $buffer[0] -eq 0xEF -and
            $buffer[1] -eq 0xBB -and
            $buffer[2] -eq 0xBF
        ) {
            $offset = 3
        }

        $encoding = New-Object System.Text.UTF8Encoding($false, $true)
        $heartbeatText = $encoding.GetString(
            $buffer,
            $offset,
            $total - $offset
        )
        $heartbeat = $heartbeatText | ConvertFrom-Json
    }
    finally {
        $stream.Dispose()
    }

    if ($heartbeat.service -cne $Service) {
        throw "SERVICE_MISMATCH"
    }

    if (
        $null -eq $heartbeat.supervisor_pid -or
        $heartbeat.supervisor_pid.GetType() -notin @([int], [long]) -or
        $heartbeat.supervisor_pid -le 0 -or
        $heartbeat.supervisor_pid -ne $ProcessId
    ) {
        throw "PID_MISMATCH"
    }

    if ($heartbeat.supervisor_phase -cnotin @("RUNNING", "SUPERVISING")) {
        throw "INVALID_PHASE"
    }

        $startedText = [string]$heartbeat.supervisor_started_at

    if ($startedText -notmatch '(Z|[+-]\d{2}:\d{2})$') {
        throw "START_TIMEZONE_MISSING"
    }

    $started = [datetimeoffset]::Parse(
        $startedText,
        [System.Globalization.CultureInfo]::InvariantCulture
    )

    if ($ProcessCreated -notmatch '(Z|[+-]\d{2}:\d{2})$') {
        throw "CREATION_TIMEZONE_MISSING"
    }

    $created = [datetimeoffset]::Parse(
        $ProcessCreated,
        [System.Globalization.CultureInfo]::InvariantCulture
    )

    if ([math]::Abs(($created - $started).TotalSeconds) -gt 5) {
        throw "CREATION_TIME_MISMATCH"
    }

        $asOfText = [string]$heartbeat.as_of

    if ($asOfText -notmatch '(Z|[+-]\d{2}:\d{2})$') {
        throw "AS_OF_TIMEZONE_MISSING"
    }

    $asOf = [datetimeoffset]::Parse(
        $asOfText,
        [System.Globalization.CultureInfo]::InvariantCulture
    )
    $age = ([datetimeoffset]::UtcNow - $asOf).TotalSeconds

    if ($age -lt -5 -or $age -gt 180) {
        throw "STALE_HEARTBEAT"
    }

    $result.verified = $true
    $result.reason = "HEARTBEAT_MATCH"
}
catch {
    # Parser/decoder exceptions may include untrusted heartbeat contents.
    # Publish only fixed reason codes, never their raw exception messages.
    $knownReasons = @(
        "HEARTBEAT_MISSING", "HEARTBEAT_TOO_LARGE", "SERVICE_MISMATCH",
        "PID_MISMATCH", "INVALID_PHASE", "START_TIMEZONE_MISSING",
        "CREATION_TIMEZONE_MISSING", "CREATION_TIME_MISMATCH",
        "AS_OF_TIMEZONE_MISSING", "STALE_HEARTBEAT"
    )
    $reason = [string]$_.Exception.Message
    $result.reason = if ($reason -cin $knownReasons) { $reason } else { "HEARTBEAT_INVALID" }
}

[pscustomobject]$result | ConvertTo-Json -Depth 4
