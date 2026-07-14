[CmdletBinding()]
param(
    [string]$Sha = "",
    [string]$DockerHost = "tcp://10.100.0.176:2375",
    [string]$PublicUrl = "https://pdca-workbench-teams.vertu.cn",
    [switch]$SkipCiCheck
)

$ErrorActionPreference = "Stop"
$ImageRegistry = "ghcr.io/frankie-foo/pdca-workbench"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$WorkbenchRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$EnvFile = Join-Path $WorkbenchRoot ".env"
$HelperImage = "vertu-registry.cn-chengdu.cr.aliyuncs.com/base/postgres:18.4-bookworm"

function Invoke-Docker {
    param([string[]]$DockerArgs)
    $output = & docker -H $DockerHost @DockerArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Remote Docker command failed: docker $($DockerArgs[0])"
    }
    return $output
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
        $state = (& docker -H $DockerHost inspect pdca-workbench `
            --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' `
            2>$null)
        if ($state -eq "healthy") { return }
        $runtimeState = (& docker -H $DockerHost inspect pdca-workbench `
            --format '{{.State.Status}}' 2>$null)
        if ($runtimeState -eq "restarting" -or $runtimeState -eq "exited") {
            throw "pdca-workbench entered state: $runtimeState"
        }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    throw "pdca-workbench did not become healthy within $TimeoutSeconds seconds"
}

function Start-PdcaContainer {
    param(
        [string]$Image,
        [string]$ReleasePath,
        [string]$Revision,
        [hashtable]$Secrets,
        [hashtable]$Agent
    )
    $dockerArgs = @(
        "run", "-d", "--name", "pdca-workbench",
        "--restart", "unless-stopped",
        "--label", "com.vertu.pdca.revision=$Revision",
        "-p", "127.0.0.1:8768:8767",
        "-v", "/opt/PDCA-agent/pdca-workbench/data:/app/data",
        "-v", "$ReleasePath/data_platform/data_role_pdca_mvp:/mvp:ro",
        "-v", "${ReleasePath}:/repo:ro",
        "-v", "/opt/PDCA-agent/pdca-workbench/vertu/vps-service.json:/root/.vertu/vps-service.json:ro",
        "-e", "PDCA_ENV=production",
        "-e", "PDCA_HOST=0.0.0.0",
        "-e", "PDCA_WORKBENCH_PORT=8767",
        "-e", "PDCA_SECRET_KEY=$($Secrets.PDCA_SECRET_KEY)",
        "-e", "PDCA_DATABASE_URL=$($Secrets.PDCA_DATABASE_URL)",
        "-e", "PDCA_MVP_ROOT=/mvp",
        "-e", "PDCA_REPO_ROOT=/repo",
        "-e", "PDCA_AUTH_MODE=hybrid",
        "-e", "PDCA_SECURE_COOKIES=1",
        "-e", "PDCA_TRUST_PROXY_HEADERS=0",
        "-e", "PDCA_CORS_ORIGINS=https://pdca-workbench-teams.vertu.cn",
        "-e", "PDCA_REQUIRE_VERTU=1",
        "-e", "PDCA_INCLUDE_DEMO_DATA=0",
        "-e", "PDCA_MAX_REPORTED_REVENUE_USD=5000000",
        "-e", "PDCA_SCHEDULER_ENABLED=1",
        "-e", "PDCA_SYNC_CRON=0 6 * * *",
        "-e", "PDCA_LOG_LEVEL=INFO",
        "-e", "VERTU_COMMAND=vertu-cli",
        "-e", "VERTU_VPS_SERVICE_URL=https://vps-service.vertu.cn",
        "-e", "VERTU_APP_ID=cursor",
        "-e", "VERTU_APP_KEY=$($Agent.VERTU_APP_KEY)",
        "-e", "VERTU_USER_LOGIN=$($Agent.VERTU_USER_LOGIN)",
        $Image
    )
    Invoke-Docker -DockerArgs $dockerArgs | Out-Null
}

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

$image = "${ImageRegistry}:$Sha"
$currentInspect = & docker -H $DockerHost inspect pdca-workbench 2>$null
$currentRevision = ""
if ($LASTEXITCODE -eq 0 -and $currentInspect) {
    $currentObject = ($currentInspect | ConvertFrom-Json)[0]
    $currentRevision = $currentObject.Config.Labels.'com.vertu.pdca.revision'
}
if ($currentRevision -eq $Sha) {
    $health = Invoke-RestMethod -Uri "$PublicUrl/health" -TimeoutSec 20
    if ($health.status -eq "ok") {
        Write-Output "Already deployed and healthy: $Sha"
        exit 0
    }
}

Write-Output "Pulling tested image $image"
Invoke-Docker -DockerArgs @("pull", $image) | Out-Null

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
        & docker -H $DockerHost rm -f $helper 2>$null | Out-Null
    }
} finally {
    Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
}
$releasePath = "/opt/PDCA-releases/$Sha"

$secrets = @{
    PDCA_SECRET_KEY = Read-DotEnvValue "PDCA_SECRET_KEY"
    PDCA_DATABASE_URL = Read-DotEnvValue "PDCA_DATABASE_URL"
}
$agent = Get-AgentCredential

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupName = "pdca-before-$($Sha.Substring(0, 8))-$stamp.dump"
$pgUrl = $secrets.PDCA_DATABASE_URL -replace '^postgresql\+psycopg2://', 'postgresql://'
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

$oldExists = (& docker -H $DockerHost ps -a --filter 'name=^/pdca-workbench$' `
    --format '{{.Names}}') -eq "pdca-workbench"
$oldImage = ""
$oldRevision = "rollback"
$oldRelease = "/opt/PDCA-agent"
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
    Start-PdcaContainer $image $releasePath $Sha $secrets $agent
    Wait-ContainerHealthy
    $health = Invoke-RestMethod -Uri "$PublicUrl/health" -TimeoutSec 25
    if ($health.status -ne "ok" -or -not $health.database_connected -or -not $health.vertu_cli.ok) {
        throw "Public health response is not fully healthy"
    }
    $login = Invoke-WebRequest -Uri "$PublicUrl/login" -UseBasicParsing -TimeoutSec 20
    if ($login.StatusCode -ne 200) { throw "Public login page smoke test failed" }
    Write-Output "Deployment healthy: $Sha"
} catch {
    & docker -H $DockerHost logs --tail 80 pdca-workbench 2>$null
    & docker -H $DockerHost rm -f pdca-workbench 2>$null | Out-Null
    if ($oldImage) {
        Write-Warning "Deployment failed; rolling back to $oldImage"
        Start-PdcaContainer $oldImage $oldRelease $oldRevision $secrets $agent
        Wait-ContainerHealthy
    }
    throw
}
