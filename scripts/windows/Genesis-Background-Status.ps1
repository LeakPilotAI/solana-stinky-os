# Genesis Background — initial read-only operational inventory.
# GB-02 foundation. No Start/Stop or ownership authority.

param(
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

$Services = @(
    "event-log",
    "api",
    "sentinel",
    "collector",
    "entities",
    "web",
    "maintain"
)

$Containers = @(
    "stinky-postgres",
    "stinky-redis",
    "stinky-minio"
)

function Get-GenesisProcessInventory {
    $rows = @(Get-CimInstance Win32_Process -ErrorAction Stop |
        Where-Object {
            $_.Name -in @("python.exe", "pythonw.exe", "node.exe")
        })

    if ($null -eq $rows) {
        throw "Native process inventory unavailable."
    }

    $result = @()

    foreach ($process in $rows) {
        $command = [string]$process.CommandLine

        if (
            $command.IndexOf(
                $Root + "\",
                [StringComparison]::OrdinalIgnoreCase
            ) -ge 0
        ) {
            $classification = "UNVERIFIED"
            $service = $null
            $heartbeatReason = "NOT_A_VERIFIED_SUPERVISOR"
            $createdUtc = $null

            $runnerMatch = [regex]::Match(
                $command,
                '(?i)(?:^|\s)"?[^"\r\n]*run_genesis_service\.py"?\s+--name\s+(event-log|api|sentinel|collector|entities|web|maintain)(?=\s|$)'
            )

            $expectedRunner = Join-Path $Root "scripts\run_genesis_service.py"
            $expectedPython = Join-Path $Root ".venv\Scripts"


            $expectedCommand = '^\s*"?' +
                [regex]::Escape($expectedPython) +
                '\\pythonw?\.exe"?\s+"' +
                [regex]::Escape($expectedRunner) +
                '"\s+--name\s+(event-log|api|sentinel|collector|entities|web|maintain)\s*$'

            $expectedExecutable = @(
                (Join-Path $expectedPython "python.exe"),
                (Join-Path $expectedPython "pythonw.exe")
            )

            $strictMatch = [regex]::Match(
                $command,
                $expectedCommand,
                [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
            )

            if (
                $strictMatch.Success -and
                $process.Name -in @("python.exe", "pythonw.exe") -and
                $process.ExecutablePath -in $expectedExecutable
            ) {
                $classification = "SUPERVISOR_CANDIDATE"
                $service = $strictMatch.Groups[1].Value
                $heartbeatReason = "NATIVE_CREATION_UNAVAILABLE"

                # Read-only heartbeat verification.
                # This does not grant process lifecycle authority.
                $createdAt = $process.CreationDate

                if (
                    $null -ne $createdAt -and
                    $createdAt.Kind -ne [System.DateTimeKind]::Unspecified
                ) {
                    $createdUtc = $createdAt.ToUniversalTime().ToString("o")
                    $verifier = Join-Path $PSScriptRoot "Genesis-Heartbeat-Verify.ps1"
                    $heartbeatReason = "HEARTBEAT_VERIFIER_UNAVAILABLE"

                    if (Test-Path -LiteralPath $verifier -PathType Leaf) {
                        try {
                            $verification = & $verifier `
                                -Service $service `
                                -ProcessId ([int]$process.ProcessId) `
                                -ProcessCreated $createdUtc |
                                ConvertFrom-Json
                            $heartbeatReason = [string]$verification.reason

                            if (
                                $null -ne $verification -and
                                $verification.verified -eq $true -and
                                $verification.reason -ceq "HEARTBEAT_MATCH"
                            ) {
                                $classification = "SUPERVISOR_VERIFIED"
                            }
                        }
                        catch {
                            # Fail closed: retain candidate classification.
                            $heartbeatReason = "HEARTBEAT_VERIFICATION_FAILED"
                        }
                    }
                }
            }

            $result += [pscustomobject]@{
                pid = [int]$process.ProcessId
                parent_pid = [int]$process.ParentProcessId
                executable = [string]$process.ExecutablePath
                created = $createdUtc
                classification = $classification
                service = $service
                heartbeat_reason = $heartbeatReason
                command_sha256 = (
                    [BitConverter]::ToString(
                        [Security.Cryptography.SHA256]::Create().ComputeHash(
                            [Text.Encoding]::UTF8.GetBytes($command)
                        )
                    ).Replace("-", "").ToLowerInvariant()
                )
                verification_scope = "EXECUTABLE_COMMAND_HEARTBEAT_NOT_LIFECYCLE_AUTHORITY"
            }
        }
    }

    return @($result)
}

function Get-GenesisDockerInventory {
    $result = @()

    foreach ($name in $Containers) {
      try {
        $raw = & docker inspect $name 2>$null

        if ($LASTEXITCODE -ne 0) {
            $result += [pscustomobject]@{
                name = $name
                state = "UNKNOWN"
                ownership = "UNVERIFIED"
                reason = "DOCKER_INSPECTION_FAILED"
            }
            continue
        }

        $records = @($raw | ConvertFrom-Json)
        if ($records.Count -ne 1) { throw "INVALID_INSPECTION_CARDINALITY" }
        $container = $records[0]
        $labels = $container.Config.Labels

        $expected = @{
            "stinky-postgres" = @{
                service = "postgres"
                volume = "project-genesis_postgres-data"
                destination = "/var/lib/postgresql/data"
                port = "5432/tcp"
                host = "5433"
            }
            "stinky-redis" = @{
                service = "redis"
                volume = "project-genesis_redis-data"
                destination = "/data"
                port = "6379/tcp"
                host = "6380"
            }
            "stinky-minio" = @{
                service = "minio"
                volume = "project-genesis_minio-data"
                destination = "/data"
                port = "9000/tcp"
                host = "9010"
            }
        }[$name]

        $workingDir = [string]$labels.'com.docker.compose.project.working_dir'
        $configFile = [string]$labels.'com.docker.compose.project.config_files'

        $validMount = @($container.Mounts | Where-Object {
            $_.Type -ceq "volume" -and
            $_.Name -ceq $expected.volume -and
            $_.Destination -ceq $expected.destination -and
            $_.RW -eq $true
        }).Count -eq 1

        $unexpectedWritable = @($container.Mounts | Where-Object {
            $_.RW -eq $true -and -not (
                $_.Type -ceq "volume" -and $_.Name -ceq $expected.volume -and
                $_.Destination -ceq $expected.destination
            )
        }).Count -gt 0

        $bindings = @($container.HostConfig.PortBindings.PSObject.Properties |
            Where-Object { $_.Name -ceq $expected.port } |
            ForEach-Object { $_.Value })
        $validPort = ($bindings.Count -eq 1 -and
            [string]$bindings[0].HostPort -ceq $expected.host)

        $owned = (
            $container.Name -ceq "/$name" -and
            $labels.'com.docker.compose.project' -ceq "project-genesis" -and
            $labels.'com.docker.compose.service' -ceq $expected.service -and
            $workingDir -ieq $Root -and
            $configFile -ieq (Join-Path $Root "docker-compose.yml") -and
            $validMount -and
            -not $unexpectedWritable -and
            $validPort -and
            $container.State.Status -in @("running", "exited", "created")
        )

        $result += [pscustomobject]@{
            name = $name
            state = [string]$container.State.Status
            ownership = if ($owned) { "PROJECT_MATCH" } else { "UNVERIFIED" }
            reason = if ($owned) { "READ_ONLY_PROJECT_MATCH" } else { "OWNERSHIP_MISMATCH" }
            container_id = [string]$container.Id
            health = if ($container.State.Health) { [string]$container.State.Health.Status } else { "UNAVAILABLE" }
        }
      }
      catch {
        $result += [pscustomobject]@{
            name = $name
            state = "UNKNOWN"
            ownership = "UNVERIFIED"
            reason = "DOCKER_INSPECTION_FAILED"
        }
      }
    }

    return @($result)
}

$InventoryError = $null
$Processes = @()

try {
    $Processes = @(Get-GenesisProcessInventory)
} catch {
    $InventoryError = "PROCESS_INVENTORY_FAILED"
}
$Docker = @(Get-GenesisDockerInventory)

# Detect multiple supervisor candidates claiming one service.
# Read-only evidence; never select a process for lifecycle control.
$DuplicateSupervisors = @(
    $Processes |
        Where-Object {
            $_.classification -in @(
                "SUPERVISOR_CANDIDATE",
                "SUPERVISOR_VERIFIED"
            ) -and
            -not [string]::IsNullOrWhiteSpace($_.service)
        } |
        Group-Object -Property service |
        Where-Object { $_.Count -gt 1 } |
        ForEach-Object {
            [pscustomobject]@{
                service = $_.Name
                count = $_.Count
                pids = @($_.Group | ForEach-Object { $_.pid })
                reason = "DUPLICATE_SUPERVISOR_CLAIM"
            }
        }
)

$DockerUnverified = @(
    $Docker | Where-Object {
        $_.state -eq "UNKNOWN" -or
        $_.ownership -ne "PROJECT_MATCH"
    }
)

$State = if ($InventoryError) {
    "ERROR"
} elseif ($DockerUnverified.Count -gt 0) {
    "ERROR"
} elseif ($Processes.Count -eq 0) {
    "STOPPED"
} else {
    "AMBIGUOUS"
}

$Result = [pscustomobject]@{
    project = "Genesis"
    state = $State
    timestamp_utc = [datetime]::UtcNow.ToString("o")
    process_count = $Processes.Count
    duplicate_supervisors = $DuplicateSupervisors
    processes = $Processes
    docker = $Docker
    services_expected = $Services
    inventory_error = $InventoryError
    lifecycle_actions = [pscustomobject]@{
        start_authorized = $false
        stop_authorized = $false
        restart_authorized = $false
        gaming_mode_authorized = $false
        reason = "READ_ONLY_FOUNDATION_LIFECYCLE_AND_RECOVERY_NOT_CERTIFIED"
    }
    note = "Read-only inventory. Process and pipeline ownership are not certified."
}

if ($Json) {
    $Result | ConvertTo-Json -Depth 8
} else {
    Write-Host "`nGENESIS BACKGROUND STATUS" -ForegroundColor Cyan
    Write-Host "State: $State"
    Write-Host "Candidate processes: $($Processes.Count)"
    $Docker | Format-Table -AutoSize
    Write-Host "Ownership and data freshness certification: PENDING"
}
