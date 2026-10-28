# Exercise the real cutover function with Docker, health and web deployment fakes.
$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot '../scripts/deploy_remote_docker.ps1'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($source, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
$cutover = $ast.Find({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Invoke-OmegaCutover' }, $true)
if (-not $cutover) { throw 'Invoke-OmegaCutover is missing' }
Invoke-Expression $cutover.Extent.Text

$script:events = [System.Collections.Generic.List[string]]::new()
$script:failure = ''
function Add-Event([string]$name) { $script:events.Add($name) }
function Start-OmegaDeploymentGate {
    Add-Event 'gate'
    if ($script:failure -eq 'active') { throw 'Deployment blocked: queued/running Omega jobs' }
    return [pscustomobject]@{ HasExited = $false }
}
function Stop-OmegaDeploymentGate { param($Gate) if ($Gate) { Add-Event 'release' } }
function Stop-ExistingOmegaWeb { param($OldWeb) Add-Event 'stop-web' }
function Invoke-Docker {
    param([string[]]$DockerArgs)
    if ($DockerArgs[0] -eq 'stop' -and $DockerArgs[-1] -eq 'main-old') { Add-Event 'stop-main' }
    elseif ($DockerArgs[0] -eq 'rename' -and $DockerArgs[1] -eq 'main-old') { Add-Event 'rename-main' }
    elseif ($DockerArgs[0] -eq 'rm' -and $DockerArgs[-1] -eq 'worker-old') { Add-Event 'cleanup-worker' }
    elseif ($DockerArgs[0] -eq 'rm' -and $DockerArgs[-1] -eq 'web-old') { Add-Event 'cleanup-web' }
    return ''
}
function Start-OmegaWorker {
    param($Image, $Revision, $Secrets, $Agent)
    Add-Event 'start-worker'
    if ($script:failure -in @('worker', 'worker-rollback-fails')) { throw 'worker failed' }
    return [pscustomobject]@{ Id = 'worker-old'; State = [pscustomobject]@{ Running = $true } }
}
function Start-PdcaContainer { Add-Event 'start-main' }
function Wait-ContainerHealthy { Add-Event 'main-health' }
function Test-ActivationSource { }
function Test-PublicMain { Add-Event 'public-main-health' }
function Test-PublicPdca { Add-Event 'main-smoke' }
function Deploy-OmegaWeb {
    Add-Event 'deploy-web'
    if ($script:failure -in @('web', 'web-lagging-failure')) { throw 'web failed' }
}
function Assert-OmegaReleaseReady { Add-Event 'accept' }
function Stop-CurrentOmegaWeb { Add-Event 'stop-current-web' }
function Stop-CurrentPdcaMain { Add-Event 'stop-current-main' }
function Restore-OmegaWorker { Add-Event 'restore-worker' }
function Restore-PdcaMain { Add-Event 'restore-main' }
function Assert-RollbackPairReady {
    Add-Event 'verify-rollback'
    if ($script:failure -eq 'worker-rollback-fails') { throw 'old worker is not running' }
}
function Restore-OmegaWeb { Add-Event 'restore-web' }

function Test-Scenario([string]$mode, [string[]]$expected, [string]$oldWebRevision = 'a', [bool]$gateOnWorker = $true) {
    $script:events.Clear()
    $script:failure = $mode
    $context = @{
        Sha = 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
        Image = 'example/image:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
        ReleasePath = '/releases/new'
        Secrets = @{}
        Agent = @{}
        LogisticsAdminUpstream = 'http://logistics.invalid'
        PublicUrl = 'https://pdca.invalid'
        OldMain = [pscustomobject]@{ Id = 'main-old'; State = [pscustomobject]@{ Running = $true } }
        OldWeb = [pscustomobject]@{ Id = 'web-old'; State = [pscustomobject]@{ Running = $true };
            Config = [pscustomobject]@{ Labels = @{ 'com.vertu.pdca.revision' = $oldWebRevision } } }
        OldOmegaEnabled = $true
        OmegaEnabled = $true
        GateOnWorker = $gateOnWorker
        OldMainRevision = 'a'
        OldWorkerRevision = 'a'
        RollbackName = 'main-rollback'
    }
    if ($mode -eq 'disabled') { $context.OmegaEnabled = $false }
    if ($mode -in @('active', 'worker', 'worker-rollback-fails', 'web', 'web-lagging-failure', 'disabled')) {
        try { Invoke-OmegaCutover -Context $context; throw 'expected cutover failure' }
        catch { if ($_.Exception.Message -eq 'expected cutover failure') { throw } }
    } else {
        Invoke-OmegaCutover -Context $context
    }
    $actual = $script:events -join ','
    $want = $expected -join ','
    if ($actual -ne $want) { throw "${mode}: expected $want; got $actual" }
}

$success = @('gate', 'stop-web', 'stop-main', 'release', 'rename-main',
    'start-worker', 'start-main', 'main-health', 'public-main-health', 'deploy-web', 'main-smoke', 'accept',
    'cleanup-worker', 'cleanup-web')
Test-Scenario 'normal' $success
Test-Scenario 'web-lagging' $success 'older-than-main'
Test-Scenario 'gate-on-main' $success 'a' $false
Test-Scenario 'disabled' @()
Test-Scenario 'active' @('gate')
Test-Scenario 'worker' @('gate', 'stop-web', 'stop-main', 'release', 'rename-main',
    'start-worker', 'stop-current-web', 'stop-current-main', 'restore-main', 'verify-rollback', 'restore-web')
Test-Scenario 'worker-rollback-fails' @('gate', 'stop-web', 'stop-main', 'release', 'rename-main',
    'start-worker', 'stop-current-web', 'stop-current-main', 'restore-main', 'verify-rollback')
Test-Scenario 'web' @('gate', 'stop-web', 'stop-main', 'release', 'rename-main',
    'start-worker', 'start-main', 'main-health', 'public-main-health', 'deploy-web',
    'stop-current-web', 'stop-current-main', 'restore-worker', 'restore-main', 'verify-rollback', 'restore-web')
Test-Scenario 'web-lagging-failure' @('gate', 'stop-web', 'stop-main', 'release', 'rename-main',
    'start-worker', 'start-main', 'main-health', 'public-main-health', 'deploy-web',
    'stop-current-web', 'stop-current-main', 'restore-worker', 'restore-main', 'verify-rollback') 'older-than-main'
Write-Output 'Omega cutover simulations: 9 passed'

# Exercise the real acceptance check: matching labels alone cannot certify report input hash.
foreach ($name in @('Get-PdcaEnvValue', 'Assert-OmegaReleaseReady')) {
    $definition = $ast.Find({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq $name }, $true)
    if (-not $definition) { throw "Missing acceptance function: $name" }
    Invoke-Expression $definition.Extent.Text
}
$rev = 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
$releaseEnv = @("PDCA_RELEASE_SHA=$rev", 'PDCA_DATABASE_URL=postgresql://unit.invalid/db',
    'PDCA_SUPERVISOR_PROVIDER=https://model.invalid', 'PDCA_SUPERVISOR_MODEL=model-v1')
$script:main = [pscustomobject]@{ State = @{ Running = $true }; Config = @{ Labels = @{ 'com.vertu.pdca.revision' = $rev }; Env = @($releaseEnv) } }
$script:worker = [pscustomobject]@{ State = @{ Status = 'running' }; Config = @{ Labels = @{ 'com.vertu.pdca.revision' = $rev }; Env = @($releaseEnv) } }
$script:web = [pscustomobject]@{ State = @{ Health = @{ Status = 'healthy' } }; Config = @{ Labels = @{ 'com.vertu.pdca.revision' = $rev }; Env = @($releaseEnv) } }
function Invoke-Docker { return (ConvertTo-Json -InputObject @($script:main) -Depth 10 -Compress) }
function Invoke-DockerProcess {
    param([string[]]$DockerArgs)
    $row = if ($DockerArgs[1] -eq 'pdca-omega-worker') { $script:worker } else { $script:web }
    return [pscustomobject]@{ ExitCode = 0; StdOut = (ConvertTo-Json -InputObject @($row) -Depth 10 -Compress) }
}
function Invoke-RestMethod {
    return [pscustomobject]@{ status = 'ok'; revision = $rev; omega_worker = @{ ok = $true } }
}
Assert-OmegaReleaseReady $rev 'https://pdca.invalid' $true
foreach ($drift in @(
    @{ Container = 'worker'; Index = 3; Value = 'PDCA_SUPERVISOR_MODEL=old-model' },
    @{ Container = 'web'; Index = 2; Value = 'PDCA_SUPERVISOR_PROVIDER=https://old.invalid' },
    @{ Container = 'web'; Index = 1; Value = 'PDCA_DATABASE_URL=postgresql://old.invalid/db' },
    @{ Container = 'web'; Index = 0; Value = 'PDCA_RELEASE_SHA=old-release' }
)) {
    $container = Get-Variable -Name $drift.Container -Scope Script -ValueOnly
    $before = $container.Config.Env[$drift.Index]
    $container.Config.Env[$drift.Index] = $drift.Value
    try {
        try { Assert-OmegaReleaseReady $rev 'https://pdca.invalid' $true; throw 'drift was accepted' }
        catch { if ($_.Exception.Message -eq 'drift was accepted') { throw } }
    } finally { $container.Config.Env[$drift.Index] = $before }
}
Write-Output 'Omega release environment acceptance: 5 passed'
