[CmdletBinding()]
param(
    [string]$Sha = "",
    [string]$DockerHost = "",
    [string]$PublicUrl = "https://pdca-workbench-teams.vertu.cn",
    [ValidateRange(1, 86400)]
    [int]$DockerCommandTimeoutSeconds = 120,
    [ValidateRange(1, 86400)]
    [int]$DockerPullTimeoutSeconds = 900,
    [string]$LogDirectory = "",
    [switch]$SkipCiCheck,
    [switch]$SkipImagePull
)

if ([string]::IsNullOrWhiteSpace($DockerHost)) {
    if ($env:PDCA_DOCKER_HOST) {
        $DockerHost = $env:PDCA_DOCKER_HOST
    } else {
        $DockerHost = "tcp://10.100.0.176:2375"
    }
}


if ($DockerHost -match '^tcp://' -and $DockerHost -notmatch ':2376$') {
    Write-Warning "DockerHost uses unencrypted Docker API ($DockerHost). Prefer TLS on port 2376, or set PDCA_DOCKER_HOST=ssh://user@host."
}


$ErrorActionPreference = "Stop"
$ImageRegistry = "ghcr.io/wfywfywfy01/pdca-workbench"
# gh 默认仓库从分支上游解析（本仓 main 跟踪 upstream/main 的历史遗留），
# 会误查上游 Frankie-Foo 的 CI；显式锁定 fork 仓库。
$CiRepo = "wfywfywfy01/PDCA-agent-wfywfywfy01"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$WorkbenchRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$EnvFile = Join-Path $WorkbenchRoot ".env"
$HelperImage = "vertu-registry.cn-chengdu.cr.aliyuncs.com/base/postgres:18.4-bookworm"
$RuntimeDataRoot = "/opt/PDCA-agent/pdca-workbench/data/runtime"
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
    $runId = "{0}-{1}" -f (Get-Date -Format "yyyyMMdd-HHmmss"), $PID
    $script:DeploymentLogPath = Join-Path $script:LogDirectory "deploy-$runId.log"
    $script:DeploymentStatePath = Join-Path $script:LogDirectory "last-run.json"
    Start-Transcript -Path $script:DeploymentLogPath -Force | Out-Null
    $script:TranscriptStarted = $true
    Write-Output "PDCA deployment run started: $runId"
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

function Read-OptionalDotEnvValue {
    param([string]$Name)
    $line = Get-Content -LiteralPath $EnvFile |
        Where-Object { $_ -match "^$([regex]::Escape($Name))=" } |
        Select-Object -Last 1
    if (-not $line) { return "" }
    $value = $line.Substring($Name.Length + 1).Trim()
    if ($value.Length -ge 2 -and
        (($value.StartsWith('"') -and $value.EndsWith('"')) -or
         ($value.StartsWith("'") -and $value.EndsWith("'")))) {
        $value = $value.Substring(1, $value.Length - 2)
    }
    return $value
}

function Get-AgentCredential {
    $lines = & vertu-cli agent env --app-id cursor --shell powershell 2>&1
    if ($LASTEXITCODE -ne 0) { throw "vertu-cli agent env failed" }
    $text = $lines -join "`n"
    $result = @{}
    foreach ($name in @("VERTU_APP_KEY", "VERTU_USER_LOGIN")) {
        $match = [regex]::Match(
            $text,
            "(?m)^\`$env:$name='((?:''|[^'])*)'\s*$"
        )
        if (-not $match.Success) { throw "vertu-cli did not return $name" }
        $result[$name] = $match.Groups[1].Value.Replace("''", "'")
    }
    return $result
}

function Wait-ContainerHealthy {
    param([int]$TimeoutSeconds = 120)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $inspect = Invoke-DockerProcess -DockerArgs @(
            "inspect", "pdca-workbench",
            "--format", "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}"
        ) -TimeoutSeconds ([Math]::Min($DockerCommandTimeoutSeconds, 30))
        $state = if ($inspect.ExitCode -eq 0) { $inspect.StdOut } else { "" }
        if ($state -eq "healthy") { return }
        $runtimeInspect = Invoke-DockerProcess -DockerArgs @(
            "inspect", "pdca-workbench", "--format", "{{.State.Status}}"
        ) -TimeoutSeconds ([Math]::Min($DockerCommandTimeoutSeconds, 30))
        $runtimeState = if ($runtimeInspect.ExitCode -eq 0) { $runtimeInspect.StdOut } else { "" }
        if ($runtimeState -eq "restarting" -or $runtimeState -eq "exited") {
            throw "pdca-workbench entered state: $runtimeState"
        }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    throw "pdca-workbench did not become healthy within $TimeoutSeconds seconds"
}

function Test-ActivationSource {
    # P0/F6 决策：激活数据暂无可自动拉取的数据源（vertu-cli 2.x 已不支持
    # odoo data sandbox，dealer_activation_stats 属已死亡查询），UI 诚实
    # 显示"无数据源"。部署时不再把该冒烟当作硬性通过条件，仅记录告警。
    $result = Invoke-DockerProcess -DockerArgs @(
        "exec", "pdca-workbench", "vertu", "odoo", "data", "sandbox",
        "--code-file", "/mvp/system_queries/dealer_activation_stats.py",
        "--timeout", "300000"
    ) -TimeoutSeconds 330
    if ($result.ExitCode -ne 0) {
        Write-Warning "Activation source smoke unavailable (expected until business provides a data channel): exit $($result.ExitCode)"
        return
    }
    try {
        $payload = $result.StdOut | ConvertFrom-Json
        $dealerCount = @($payload.execution.result.dealers).Count
        Write-Output "Activation source healthy: $dealerCount dealers"
    } catch {
        Write-Warning "Activation source smoke returned invalid JSON (non-fatal): $($_.Exception.Message)"
    }
}

function New-SecretEnvFile {
    param(
        [hashtable]$Secrets,
        [hashtable]$Agent
    )
    $path = Join-Path $env:TEMP ("pdca-docker-secrets-{0}.env" -f ([guid]::NewGuid().ToString("N")))
    $lines = @(
        "PDCA_SECRET_KEY=$($Secrets.PDCA_SECRET_KEY)",
        "PDCA_DATABASE_URL=$($Secrets.PDCA_DATABASE_URL)",
        "VERTU_APP_KEY=$($Agent.VERTU_APP_KEY)",
        "VERTU_USER_LOGIN=$($Agent.VERTU_USER_LOGIN)"
    )
    if ($Secrets.VERTU_BOT_INBOUND_KEY) {
        $lines += "VERTU_BOT_INBOUND_KEY=$($Secrets.VERTU_BOT_INBOUND_KEY)"
    }
    [System.IO.File]::WriteAllLines($path, $lines)
    return $path
}


function Start-PdcaContainer {
    param(
        [string]$Image,
        [string]$ReleasePath,
        [string]$Revision,
        [hashtable]$Secrets,
        [hashtable]$Agent
    )
    $secretEnvFile = New-SecretEnvFile -Secrets $Secrets -Agent $Agent
    try {

    $dockerArgs = @(
        "run", "-d", "--name", "pdca-workbench",
        "--restart", "unless-stopped",
        "--label", "com.vertu.pdca.revision=$Revision",
        "-p", "127.0.0.1:8768:8767",
        "--mount", "type=volume,src=pdca-vertu-session,dst=/root/.vertu",
        "-v", "/opt/PDCA-agent/pdca-workbench/data:/app/data",
        "-v", "$ReleasePath/data_platform/data_role_pdca_mvp:/mvp:ro",
        "-v", "${RuntimeDataRoot}/inputs:/mvp/inputs",
        "-v", "${RuntimeDataRoot}/outputs:/mvp/outputs",
        "-v", "${RuntimeDataRoot}/outbox:/mvp/outbox",
        "-v", "${ReleasePath}:/repo:ro",
        "-v", "/opt/PDCA-agent/pdca-workbench/vertu/vps-service.json:/root/.vertu/vps-service.json:ro",
        "--env-file", $secretEnvFile,

        "-e", "PDCA_ENV=production",
        "-e", "TZ=Asia/Shanghai",
        "-e", "PDCA_HOST=0.0.0.0",
        "-e", "PDCA_WORKBENCH_PORT=8767",

        "-e", "PDCA_MVP_ROOT=/mvp",
        "-e", "PDCA_REPO_ROOT=/repo",
        "-e", "PDCA_AUTH_MODE=hybrid",
        "-e", "PDCA_SECURE_COOKIES=1",
        "-e", "PDCA_TRUST_PROXY_HEADERS=0",
        "-e", "PDCA_CORS_ORIGINS=https://pdca-workbench-teams.vertu.cn",
        "-e", "PDCA_REQUIRE_VERTU=1",
        "-e", "PDCA_INCLUDE_DEMO_DATA=0",
        "-e", "PDCA_BOOTSTRAP_ADMIN_USERNAME=",
        "-e", "PDCA_BOOTSTRAP_ADMIN_PASSWORD=",
        "-e", "PDCA_MAX_REPORTED_REVENUE_USD=5000000",
        "-e", "PDCA_REVENUE_REVIEW_THRESHOLD_USD=1000000",
        "-e", "PDCA_SCHEDULER_ENABLED=1",
        "-e", "PDCA_SYNC_CRON=0 6 * * *",
        "-e", "PDCA_LOG_LEVEL=INFO",
        "-e", "VERTU_COMMAND=vertu-cli",
        "-e", "VERTU_LEGACY_COMMAND=vertu",
        "-e", "VERTU_VPS_SERVICE_URL=https://vps-service.vertu.cn",
        "-e", "VERTU_APP_ID=cursor"
    )
    # P1/P5：可选业务开关从 .env 透传（未配置则保持默认行为）
    $homeRedirect = Read-OptionalDotEnvValue "PDCA_HOME_REDIRECT"
    if ($homeRedirect) { $dockerArgs += @("-e", "PDCA_HOME_REDIRECT=$homeRedirect") }
    $alertWebhook = Read-OptionalDotEnvValue "PDCA_ALERT_WEBHOOK_URL"
    if ($alertWebhook) { $dockerArgs += @("-e", "PDCA_ALERT_WEBHOOK_URL=$alertWebhook") }
    $dockerArgs += $Image
    Invoke-Docker -DockerArgs $dockerArgs | Out-Null
    }
    finally {
        Remove-Item -LiteralPath $secretEnvFile -Force -ErrorAction SilentlyContinue
    }
}

function Initialize-RemoteRuntimeDirectories {
    param([string]$ReleasePath)
    Invoke-Docker -DockerArgs @(
        "run", "--rm", "--entrypoint", "sh",
        "-v", "/opt/PDCA-agent/pdca-workbench/data:/pdca-data",
        "-v", "$ReleasePath/data_platform/data_role_pdca_mvp:/mvp-release:ro",
        $HelperImage, "-lc",
        'set -eu; mkdir -p /pdca-data/runtime; for name in inputs outputs outbox; do dest="/pdca-data/runtime/$name"; src="/mvp-release/$name"; mkdir -p "$dest"; if [ -d "$src" ] && [ -z "$(find "$dest" -mindepth 1 -maxdepth 1 -print -quit)" ]; then cp -a "$src/." "$dest/"; fi; chmod 700 "$dest"; done; chmod 700 /pdca-data/runtime'
    ) | Out-Null
}

trap {
    $failureMessage = Protect-DeploymentText $_.Exception.Message
    Write-Output "PDCA deployment failed: $failureMessage"
    Write-Output "Diagnostic log: $script:DeploymentLogPath"
    try { Complete-DeploymentRun -Status "failed" -Message $failureMessage } catch { }
    [Console]::Error.WriteLine("PDCA deployment failed: $failureMessage")
    [Console]::Error.WriteLine("Diagnostic log: $script:DeploymentLogPath")
    exit 1
}

Initialize-DeploymentLog

if (-not (Test-Path -LiteralPath $EnvFile)) {
    throw "Missing untracked production environment file: $EnvFile"
}

if (-not $Sha) {
    $run = gh run list --repo $CiRepo --workflow pdca-ci-cd.yml --branch main --status success `
        --limit 1 --json headSha,conclusion | ConvertFrom-Json
    if (-not $run -or $run.conclusion -ne "success") {
        throw "No successful main PDCA CI/CD run found"
    }
    $Sha = $run.headSha
}
if ($Sha -notmatch '^[0-9a-f]{40}$') { throw "Sha must be a full 40-character commit" }

if (-not $SkipCiCheck) {
    # gh run list 的 --commit / --status 过滤均存在漏报怪癖；显式 --repo 锁定
    # fork（默认解析会跟到 upstream），拉取最近 10 条 run 后精确匹配 headSha。
    $runs = gh run list --repo $CiRepo --workflow pdca-ci-cd.yml --branch main `
        --limit 10 --json headSha,conclusion | ConvertFrom-Json
    $matched = @($runs | Where-Object { $_.headSha -eq $Sha -and $_.conclusion -eq "success" })
    if (-not $matched) {
        throw "CI is not green for $Sha"
    }
}

$image = "${ImageRegistry}:$Sha"
$currentInspectResult = Invoke-DockerProcess -DockerArgs @("inspect", "pdca-workbench")
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

if ($SkipImagePull) {
    Write-Output "Using preloaded tested image $image"
    $imageInspectResult = Invoke-DockerProcess -DockerArgs @("image", "inspect", $image)
    if ($imageInspectResult.ExitCode -ne 0 -or -not $imageInspectResult.StdOut) {
        throw "Preloaded image is missing: $image"
    }
    $imageObject = ($imageInspectResult.StdOut | ConvertFrom-Json)[0]
    $sourceRevision = $imageObject.Config.Labels.'com.vertu.pdca.source_revision'
    if ($sourceRevision -and $sourceRevision -ne $Sha) {
        throw "Preloaded image revision mismatch: expected $Sha"
    }
    if (-not $sourceRevision) {
        Write-Warning "Preloaded image lacks the source_revision label; relying on explicit -Sha and digest pinning"
    }
} else {
    Write-Output "Pulling tested image $image"
    Invoke-Docker -DockerArgs @("pull", $image) -TimeoutSeconds $DockerPullTimeoutSeconds | Out-Null
}

Write-Output "Preparing immutable release directory for $Sha"
& git -C $RepoRoot fetch --no-tags origin $Sha
if ($LASTEXITCODE -ne 0) { throw "git fetch failed for $Sha" }
$archive = Join-Path $env:TEMP "pdca-release-$Sha.tar"
try {
    & git -C $RepoRoot archive --format=tar --output=$archive $Sha
    if ($LASTEXITCODE -ne 0) { throw "git archive failed for $Sha" }
    $helperArgs = @(
        "create", "--entrypoint", "sh",
        "-v", "/opt/PDCA-releases:/releases",
        $HelperImage, "-lc",
        "set -eu; mkdir -p '/releases/$Sha'; tar -xf /tmp/release.tar -C '/releases/$Sha'; printf '%s\n' '$Sha' > '/releases/$Sha/.pdca-release'"
    )
    $helper = (Invoke-Docker -DockerArgs $helperArgs).Trim()
    try {
        Invoke-Docker -DockerArgs @("cp", $archive, "${helper}:/tmp/release.tar") | Out-Null
        Invoke-Docker -DockerArgs @("start", "-a", $helper) | Out-Null
    } finally {
        try {
            Invoke-DockerProcess -DockerArgs @("rm", "-f", $helper) `
                -TimeoutSeconds ([Math]::Min($DockerCommandTimeoutSeconds, 30)) | Out-Null
        } catch {
            Write-Warning "Unable to remove release helper container: $($_.Exception.Message)"
        }
    }
} finally {
    Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
}
$releasePath = "/opt/PDCA-releases/$Sha"

$secrets = @{
    PDCA_SECRET_KEY = Read-DotEnvValue "PDCA_SECRET_KEY"
    PDCA_DATABASE_URL = Read-DotEnvValue "PDCA_DATABASE_URL"
    VERTU_BOT_INBOUND_KEY = Read-OptionalDotEnvValue "VERTU_BOT_INBOUND_KEY"
}
if (-not $secrets.VERTU_BOT_INBOUND_KEY) {
    Write-Output "VERTU_BOT_INBOUND_KEY is not set; using the persisted pdca-vertu-session login"
}
$agent = Get-AgentCredential
$script:SensitiveValues = @(
    $secrets.PDCA_SECRET_KEY,
    $secrets.PDCA_DATABASE_URL,
    $agent.VERTU_APP_KEY,
    $secrets.VERTU_BOT_INBOUND_KEY
)

Write-Output "Ensuring writable PDCA runtime directories"
Initialize-RemoteRuntimeDirectories -ReleasePath $releasePath

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupName = "pdca-before-$($Sha.Substring(0, 8))-$stamp.dump"
$pgUrl = $secrets.PDCA_DATABASE_URL -replace '^postgresql\+psycopg2://', 'postgresql://'
$script:SensitiveValues += $pgUrl
Write-Output "Creating PostgreSQL backup: $backupName"
Invoke-Docker -DockerArgs @(
    "run", "--rm", "--entrypoint", "pg_dump",
    "-v", "/opt/PDCA-agent/pdca-workbench/backups:/backups",
    $HelperImage, $pgUrl, "--format=custom", "--file=/backups/$backupName"
) | Out-Null
Invoke-Docker -DockerArgs @(
    "run", "--rm", "--entrypoint", "sh",
    "-v", "/opt/PDCA-agent/pdca-workbench/backups:/backups",
    $HelperImage, "-lc", "chmod 600 '/backups/$backupName'"
) | Out-Null

$oldContainerResult = Invoke-DockerProcess -DockerArgs @(
    "ps", "-a", "--filter", "name=^/pdca-workbench$", "--format", "{{.Names}}"
)
if ($oldContainerResult.ExitCode -ne 0) {
    throw "Unable to inspect the existing PDCA container: $($oldContainerResult.StdErr)"
}
$oldExists = $oldContainerResult.StdOut -eq "pdca-workbench"
$oldImage = ""
$oldRevision = "rollback"
$oldRelease = "/opt/PDCA-agent"
Write-Output "Inspecting the currently deployed PDCA container"
if ($oldExists) {
    $oldObject = ((Invoke-Docker -DockerArgs @("inspect", "pdca-workbench")) | ConvertFrom-Json)[0]
    $oldImage = $oldObject.Config.Image
    $candidateRevision = $oldObject.Config.Labels.'com.vertu.pdca.revision'
    if ($candidateRevision) { $oldRevision = $candidateRevision }
    $candidateRelease = ($oldObject.Mounts | Where-Object { $_.Destination -eq "/repo" } |
        Select-Object -First 1).Source
    if ($candidateRelease) { $oldRelease = $candidateRelease }
    Invoke-Docker -DockerArgs @("rm", "-f", "pdca-workbench") | Out-Null
}

try {
    Write-Output "Starting PDCA container for $Sha"
    Start-PdcaContainer $image $releasePath $Sha $secrets $agent
    Write-Output "Waiting for container health"
    Wait-ContainerHealthy
    Write-Output "Validating activation source through the legacy fallback"
    Test-ActivationSource
    Write-Output "Running public health and login smoke checks"
    $health = Invoke-RestMethod -Uri "$PublicUrl/health" -TimeoutSec 25
    if ($health.status -ne "ok" -or -not $health.database_connected -or -not $health.vertu_cli.ok) {
        throw "Public health response is not fully healthy"
    }
    $login = Invoke-WebRequest -Uri "$PublicUrl/login" -UseBasicParsing -TimeoutSec 20
    if ($login.StatusCode -ne 200) { throw "Public login page smoke test failed" }
    Write-Output "Deployment healthy: $Sha"
} catch {
    try {
        $failedLogs = Invoke-DockerProcess -DockerArgs @("logs", "--tail", "80", "pdca-workbench") `
            -TimeoutSeconds ([Math]::Min($DockerCommandTimeoutSeconds, 30))
        if ($failedLogs.StdOut) { Write-Output (Protect-DeploymentText $failedLogs.StdOut) }
        if ($failedLogs.StdErr) {
            [Console]::Error.WriteLine((Protect-DeploymentText $failedLogs.StdErr))
        }
    } catch {
        Write-Warning "Unable to collect failed container logs: $($_.Exception.Message)"
    }
    try {
        Invoke-DockerProcess -DockerArgs @("rm", "-f", "pdca-workbench") `
            -TimeoutSeconds ([Math]::Min($DockerCommandTimeoutSeconds, 30)) | Out-Null
    } catch {
        Write-Warning "Unable to remove failed container: $($_.Exception.Message)"
    }
    if ($oldImage) {
        Write-Warning "Deployment failed; rolling back to $oldImage"
        Start-PdcaContainer $oldImage $oldRelease $oldRevision $secrets $agent
        Wait-ContainerHealthy
    }
    throw
}

Complete-DeploymentRun -Status "success" -Message "Deployment healthy: $Sha"
