[CmdletBinding()]
param(
    [string]$Sha = "",
    [string]$DockerHost = "tcp://10.100.0.176:2375",
    [string]$PublicUrl = "https://pdca-workbench.vertu.cn",
    [ValidateRange(1, 86400)]
    [int]$DockerCommandTimeoutSeconds = 120,
    [ValidateRange(1, 86400)]
    [int]$DockerPullTimeoutSeconds = 900,
    [string]$LogDirectory = "",
    [switch]$SkipCiCheck
)

# Standalone deploy script for the walkin-submit (dealer daily five-kit entry) portal.
#
# Key differences from deploy_remote_docker.ps1 (the internal PDCA workbench, pdca-workbench
# container):
# - Container name pdca-walkin-portal, host port 127.0.0.1:8769 (internal workbench uses
#   8768, so the two never collide).
# - Does not mount /mvp or /repo -- walkin-submit does not depend on the MVP dashboard
#   data (confirmed in the deployment manual), so this script skips the entire git archive /
#   per-SHA release-directory staging step used by the internal workbench deploy.
# - PDCA_AUTH_MODE=local, PDCA_REQUIRE_VERTU=0, PDCA_SCHEDULER_ENABLED=0 -- no vertu-cli
#   credentials needed (no Get-AgentCredential / vertu-cli agent env call).
# - Separate .env.walkin secrets file and separate backup directory; nothing is shared
#   with the internal workbench's deploy path.
#
# Both containers share the same production Postgres database and the same code image
# (ghcr.io/frankie-foo/pdca-workbench), but run as two fully independent processes --
# restarting/redeploying one never touches the other.

$ErrorActionPreference = "Stop"
$ImageRegistry = "ghcr.io/frankie-foo/pdca-workbench"
$WorkbenchRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$EnvFile = Join-Path $WorkbenchRoot ".env.walkin"
$HelperImage = "vertu-registry.cn-chengdu.cr.aliyuncs.com/base/postgres:18.4-bookworm"
$ContainerName = "pdca-walkin-portal"
$HostPort = 8769
$BackupDir = "/opt/PDCA-agent/pdca-workbench/backups-walkin"
$DataDir = "/opt/PDCA-agent/pdca-workbench/data-walkin"
$script:RunStartedAt = Get-Date
$script:DeploymentLogPath = ""
$script:DeploymentStatePath = ""
$script:TranscriptStarted = $false
$script:SensitiveValues = @()

function Protect-DeploymentText {
    param([AllowNull()][string]$Text)
    if ($null -eq $Text) { return "" }
    $protected = $Text
    foreach ($value in $script:SensitiveValues) {
        if ($value) { $protected = $protected.Replace([string]$value, "[REDACTED]") }
    }
    return $protected
}

function ConvertTo-NativeArgument {
    param([AllowEmptyString()][string]$Value)
    if ($Value.Length -eq 0) { return '""' }
    if ($Value -notmatch '[\s"]') { return $Value }

    $builder = New-Object System.Text.StringBuilder
    [void]$builder.Append('"')
    $backslashes = 0
    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq '\') {
            $backslashes++
            continue
        }
        if ($character -eq '"') {
            [void]$builder.Append(('\' * (($backslashes * 2) + 1)))
            [void]$builder.Append('"')
        } else {
            if ($backslashes -gt 0) {
                [void]$builder.Append(('\' * $backslashes))
            }
            [void]$builder.Append($character)
        }
        $backslashes = 0
    }
    if ($backslashes -gt 0) {
        [void]$builder.Append(('\' * ($backslashes * 2)))
    }
    [void]$builder.Append('"')
    return $builder.ToString()
}

function Invoke-DockerProcess {
    param(
        [string[]]$DockerArgs,
        [int]$TimeoutSeconds = $DockerCommandTimeoutSeconds
    )
    $allArgs = @("-H", $DockerHost) + $DockerArgs
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = "docker"
    $startInfo.Arguments = (($allArgs | ForEach-Object { ConvertTo-NativeArgument $_ }) -join " ")
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    try {
        if (-not $process.Start()) { throw "Unable to start Docker CLI" }
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            try {
                $process.Kill()
                if (-not $process.WaitForExit(5000)) {
                    throw "Docker CLI did not exit after it was killed"
                }
            } catch {
                throw "Remote Docker command timed out after $TimeoutSeconds seconds and could not be terminated: $($_.Exception.Message)"
            }
            throw "Remote Docker command timed out after $TimeoutSeconds seconds: docker $($DockerArgs[0])"
        }
        $stdout = $stdoutTask.GetAwaiter().GetResult()
        $stderr = $stderrTask.GetAwaiter().GetResult()
        return [pscustomobject]@{
            ExitCode = $process.ExitCode
            StdOut = $stdout.TrimEnd("`r", "`n")
            StdErr = $stderr.TrimEnd("`r", "`n")
        }
    } finally {
        $process.Dispose()
    }
}

function Invoke-Docker {
    param(
        [string[]]$DockerArgs,
        [int]$TimeoutSeconds = $DockerCommandTimeoutSeconds
    )
    $result = Invoke-DockerProcess -DockerArgs $DockerArgs -TimeoutSeconds $TimeoutSeconds
    if ($result.ExitCode -ne 0) {
        $safeError = Protect-DeploymentText $result.StdErr
        $detail = if ($safeError) { ": $safeError" } else { "" }
        throw "Remote Docker command failed with exit code $($result.ExitCode): docker $($DockerArgs[0])$detail"
    }
    return $result.StdOut
}

function Complete-DeploymentRun {
    param(
        [ValidateSet("success", "failed")][string]$Status,
        [string]$Message
    )
    $state = [ordered]@{
        status = $Status
        started_at = $script:RunStartedAt.ToString("o")
        finished_at = (Get-Date).ToString("o")
        sha = $Sha
        docker_host = $DockerHost
        public_url = $PublicUrl
        message = Protect-DeploymentText $Message
        log_path = $script:DeploymentLogPath
    }
    if ($script:DeploymentStatePath) {
        $state | ConvertTo-Json | Set-Content -LiteralPath $script:DeploymentStatePath -Encoding UTF8
    }
    if ($script:TranscriptStarted) {
        Stop-Transcript | Out-Null
        $script:TranscriptStarted = $false
    }
}

function Initialize-DeploymentLog {
    if (-not $LogDirectory) {
        $baseDirectory = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { $env:TEMP }
        $script:LogDirectory = Join-Path $baseDirectory "PDCA\deploy-logs"
    } else {
        $script:LogDirectory = $LogDirectory
    }
    New-Item -ItemType Directory -Path $script:LogDirectory -Force | Out-Null
    $runId = "walkin-{0}-{1}" -f (Get-Date -Format "yyyyMMdd-HHmmss"), $PID
    $script:DeploymentLogPath = Join-Path $script:LogDirectory "deploy-$runId.log"
    $script:DeploymentStatePath = Join-Path $script:LogDirectory "last-run-walkin.json"
    Start-Transcript -Path $script:DeploymentLogPath -Force | Out-Null
    $script:TranscriptStarted = $true
    Write-Output "PDCA walkin-portal deployment run started: $runId"
    Write-Output "Persistent log: $script:DeploymentLogPath"
}

function Read-DotEnvValue {
    param([string]$Name)
    $line = Get-Content -LiteralPath $EnvFile |
        Where-Object { $_ -match "^$([regex]::Escape($Name))=" } |
        Select-Object -Last 1
    if (-not $line) { throw "Missing $Name in $EnvFile" }
    $value = $line.Substring($Name.Length + 1).Trim()
    if ($value.Length -ge 2 -and
        (($value.StartsWith('"') -and $value.EndsWith('"')) -or
         ($value.StartsWith("'") -and $value.EndsWith("'")))) {
        $value = $value.Substring(1, $value.Length - 2)
    }
    if (-not $value) { throw "Empty $Name in $EnvFile" }
    return $value
}

function Wait-ContainerHealthy {
    param([int]$TimeoutSeconds = 120)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $inspect = Invoke-DockerProcess -DockerArgs @(
            "inspect", $ContainerName,
            "--format", "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}"
        ) -TimeoutSeconds ([Math]::Min($DockerCommandTimeoutSeconds, 30))
        $state = if ($inspect.ExitCode -eq 0) { $inspect.StdOut } else { "" }
        if ($state -eq "healthy") { return }
        $runtimeInspect = Invoke-DockerProcess -DockerArgs @(
            "inspect", $ContainerName, "--format", "{{.State.Status}}"
        ) -TimeoutSeconds ([Math]::Min($DockerCommandTimeoutSeconds, 30))
        $runtimeState = if ($runtimeInspect.ExitCode -eq 0) { $runtimeInspect.StdOut } else { "" }
        if ($runtimeState -eq "restarting" -or $runtimeState -eq "exited") {
            throw "$ContainerName entered state: $runtimeState"
        }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    throw "$ContainerName did not become healthy within $TimeoutSeconds seconds"
}

function Start-PdcaWalkinContainer {
    param(
        [string]$Image,
        [string]$Revision,
        [hashtable]$Secrets
    )
    $dockerArgs = @(
        "run", "-d", "--name", $ContainerName,
        "--restart", "unless-stopped",
        "--label", "com.vertu.pdca.revision=$Revision",
        "-p", "127.0.0.1:${HostPort}:8767",
        "-v", "${DataDir}:/app/data",
        "-e", "PDCA_ENV=production",
        "-e", "PDCA_HOST=0.0.0.0",
        "-e", "PDCA_WORKBENCH_PORT=8767",
        "-e", "PDCA_SECRET_KEY=$($Secrets.PDCA_WALKIN_SECRET_KEY)",
        "-e", "PDCA_DATABASE_URL=$($Secrets.PDCA_DATABASE_URL)",
        "-e", "PDCA_AUTH_MODE=local",
        "-e", "PDCA_SECURE_COOKIES=1",
        "-e", "PDCA_TRUST_PROXY_HEADERS=0",
        "-e", "PDCA_CORS_ORIGINS=https://pdca-workbench.vertu.cn",
        "-e", "PDCA_REQUIRE_VERTU=0",
        "-e", "PDCA_INCLUDE_DEMO_DATA=0",
        "-e", "PDCA_MAX_REPORTED_REVENUE_USD=5000000",
        "-e", "PDCA_SCHEDULER_ENABLED=0",
        "-e", "PDCA_LOG_LEVEL=INFO",
        $Image
    )
    Invoke-Docker -DockerArgs $dockerArgs | Out-Null
}

trap {
    $failureMessage = Protect-DeploymentText $_.Exception.Message
    Write-Output "PDCA walkin-portal deployment failed: $failureMessage"
    Write-Output "Diagnostic log: $script:DeploymentLogPath"
    try { Complete-DeploymentRun -Status "failed" -Message $failureMessage } catch { }
    [Console]::Error.WriteLine("PDCA walkin-portal deployment failed: $failureMessage")
    [Console]::Error.WriteLine("Diagnostic log: $script:DeploymentLogPath")
    exit 1
}

Initialize-DeploymentLog

if (-not (Test-Path -LiteralPath $EnvFile)) {
    throw "Missing untracked production environment file: $EnvFile"
}

if (-not $Sha) {
    $run = gh run list --workflow pdca-ci-cd.yml --branch main --status success `
        --limit 1 --json headSha,conclusion | ConvertFrom-Json
    if (-not $run -or $run.conclusion -ne "success") {
        throw "No successful main PDCA CI/CD run found"
    }
    $Sha = $run.headSha
}
if ($Sha -notmatch '^[0-9a-f]{40}$') { throw "Sha must be a full 40-character commit" }

if (-not $SkipCiCheck) {
    $run = gh run list --workflow pdca-ci-cd.yml --commit $Sha --limit 1 `
        --json status,conclusion,headSha | ConvertFrom-Json
    if (-not $run -or $run.status -ne "completed" -or $run.conclusion -ne "success") {
        throw "CI is not green for $Sha"
    }
}

# Reuse the same GHCR image the internal workbench deploy already published (same code),
# just start a second, independent container from it.
$image = "${ImageRegistry}:$Sha"
$currentInspectResult = Invoke-DockerProcess -DockerArgs @("inspect", $ContainerName)
$currentInspect = $currentInspectResult.StdOut
$currentRevision = ""
if ($currentInspectResult.ExitCode -eq 0 -and $currentInspect) {
    $currentObject = ($currentInspect | ConvertFrom-Json)[0]
    $currentRevision = $currentObject.Config.Labels.'com.vertu.pdca.revision'
}
if ($currentRevision -eq $Sha) {
    $health = Invoke-RestMethod -Uri "$PublicUrl/health" -TimeoutSec 20
    if ($health.status -eq "ok") {
        Write-Output "Already deployed and healthy: $Sha"
        Complete-DeploymentRun -Status "success" -Message "Already deployed and healthy: $Sha"
        exit 0
    }
}

Write-Output "Pulling tested image $image"
Invoke-Docker -DockerArgs @("pull", $image) -TimeoutSeconds $DockerPullTimeoutSeconds | Out-Null

$secrets = @{
    PDCA_WALKIN_SECRET_KEY = Read-DotEnvValue "PDCA_WALKIN_SECRET_KEY"
    PDCA_DATABASE_URL = Read-DotEnvValue "PDCA_DATABASE_URL"
}
$script:SensitiveValues = @(
    $secrets.PDCA_WALKIN_SECRET_KEY,
    $secrets.PDCA_DATABASE_URL
)

Write-Output "Ensuring writable data directory on remote host"
Invoke-Docker -DockerArgs @(
    "run", "--rm", "--entrypoint", "sh",
    "-v", "${DataDir}:/pdca-walkin-data",
    $HelperImage, "-lc", "mkdir -p /pdca-walkin-data && chmod 700 /pdca-walkin-data"
) | Out-Null

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupName = "pdca-walkin-before-$($Sha.Substring(0, 8))-$stamp.dump"
$pgUrl = $secrets.PDCA_DATABASE_URL -replace '^postgresql\+psycopg2://', 'postgresql://'
$script:SensitiveValues += $pgUrl
Write-Output "Creating PostgreSQL backup: $backupName"
Invoke-Docker -DockerArgs @(
    "run", "--rm", "--entrypoint", "sh",
    "-v", "${BackupDir}:/backups",
    $HelperImage, "-lc", "mkdir -p /backups"
) | Out-Null
Invoke-Docker -DockerArgs @(
    "run", "--rm", "--entrypoint", "pg_dump",
    "-v", "${BackupDir}:/backups",
    $HelperImage, $pgUrl, "--format=custom", "--file=/backups/$backupName"
) | Out-Null
Invoke-Docker -DockerArgs @(
    "run", "--rm", "--entrypoint", "sh",
    "-v", "${BackupDir}:/backups",
    $HelperImage, "-lc", "chmod 600 '/backups/$backupName'"
) | Out-Null

$oldContainerResult = Invoke-DockerProcess -DockerArgs @(
    "ps", "-a", "--filter", "name=^/${ContainerName}$", "--format", "{{.Names}}"
)
if ($oldContainerResult.ExitCode -ne 0) {
    throw "Unable to inspect the existing $ContainerName container: $($oldContainerResult.StdErr)"
}
$oldExists = $oldContainerResult.StdOut -eq $ContainerName
$oldImage = ""
$oldRevision = "rollback"
Write-Output "Inspecting the currently deployed $ContainerName container"
if ($oldExists) {
    $oldObject = ((Invoke-Docker -DockerArgs @("inspect", $ContainerName)) | ConvertFrom-Json)[0]
    $oldImage = $oldObject.Config.Image
    $candidateRevision = $oldObject.Config.Labels.'com.vertu.pdca.revision'
    if ($candidateRevision) { $oldRevision = $candidateRevision }
    Invoke-Docker -DockerArgs @("rm", "-f", $ContainerName) | Out-Null
}

try {
    Write-Output "Starting $ContainerName for $Sha"
    Start-PdcaWalkinContainer $image $Sha $secrets
    Write-Output "Waiting for container health"
    Wait-ContainerHealthy
    Write-Output "Running public health and login smoke checks"
    $health = Invoke-RestMethod -Uri "$PublicUrl/health" -TimeoutSec 25
    # This container runs with PDCA_REQUIRE_VERTU=0, so health.vertu_cli.ok is expected
    # to be false/unavailable -- unlike the internal workbench deploy script, do not treat
    # it as a failure condition. The app's own /health "status" field already accounts for
    # vertu_required=false correctly, so checking status + database_connected is sufficient.
    if ($health.status -ne "ok" -or -not $health.database_connected) {
        throw "Public health response is not fully healthy"
    }
    $login = Invoke-WebRequest -Uri "$PublicUrl/login" -UseBasicParsing -TimeoutSec 20
    if ($login.StatusCode -ne 200) { throw "Public login page smoke test failed" }
    $walkinSubmit = Invoke-WebRequest -Uri "$PublicUrl/walkin-submit" -UseBasicParsing -TimeoutSec 20
    if ($walkinSubmit.StatusCode -ne 200 -and $walkinSubmit.StatusCode -ne 307) {
        throw "Public walkin-submit page smoke test failed"
    }
    Write-Output "Deployment healthy: $Sha"
} catch {
    try {
        $failedLogs = Invoke-DockerProcess -DockerArgs @("logs", "--tail", "80", $ContainerName) `
            -TimeoutSeconds ([Math]::Min($DockerCommandTimeoutSeconds, 30))
        if ($failedLogs.StdOut) { Write-Output (Protect-DeploymentText $failedLogs.StdOut) }
        if ($failedLogs.StdErr) {
            [Console]::Error.WriteLine((Protect-DeploymentText $failedLogs.StdErr))
        }
    } catch {
        Write-Warning "Unable to collect failed container logs: $($_.Exception.Message)"
    }
    try {
        Invoke-DockerProcess -DockerArgs @("rm", "-f", $ContainerName) `
            -TimeoutSeconds ([Math]::Min($DockerCommandTimeoutSeconds, 30)) | Out-Null
    } catch {
        Write-Warning "Unable to remove failed container: $($_.Exception.Message)"
    }
    if ($oldImage) {
        Write-Warning "Deployment failed; rolling back to $oldImage"
        Start-PdcaWalkinContainer $oldImage $oldRevision $secrets
        Wait-ContainerHealthy
    }
    throw
}

Complete-DeploymentRun -Status "success" -Message "Deployment healthy: $Sha"
