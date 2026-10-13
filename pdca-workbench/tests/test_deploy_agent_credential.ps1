$ErrorActionPreference = 'Stop'
$path = Join-Path $PSScriptRoot '..\scripts\deploy_remote_docker.ps1'
$errors = $null
$tokens = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$errors)
if ($errors) { throw 'Deployment script has PowerShell parse errors' }
$definition = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Get-AgentCredential'
}, $true)
if (-not $definition) { throw 'Get-AgentCredential missing' }
Invoke-Expression $definition.Extent.Text

$script:currentObject = [pscustomobject]@{
    Config = [pscustomobject]@{
        Env = @('VERTU_APP_ID=cursor', 'VERTU_APP_KEY=vta_old', 'VERTU_USER_LOGIN=frank@example.com')
    }
}
$script:DockerHost = 'ssh://pdca-docker-176'
$script:RefreshAgentCredential = $false
$result = Get-AgentCredential
if ($result.VERTU_APP_KEY -cne 'vta_old') { throw 'Default deployment changed the existing key' }

function vps-work {
    $global:LASTEXITCODE = 0
    '$env:VERTU_APP_ID=''cursor'''
    '$env:VERTU_APP_KEY=''vta_new'''
    '$env:VERTU_USER_LOGIN=''frank@example.com'''
}
function Invoke-RestMethod {
    param($Uri, $Headers, $TimeoutSec)
    if ($Headers.Authorization -cne 'Bearer vta_new') { throw 'Wrong key used for identity check' }
    return [pscustomobject]@{ user = [pscustomobject]@{ login = 'frank@example.com' } }
}

$script:RefreshAgentCredential = $true
$script:DockerHost = 'tcp://10.100.0.176:2375'
try {
    Get-AgentCredential | Out-Null
    throw 'Unencrypted Docker transport was accepted'
} catch {
    if ($_.Exception.Message -notmatch 'requires SSH Docker transport') { throw }
}

$script:DockerHost = 'ssh://pdca-docker-176'
$result = Get-AgentCredential
if ($result.VERTU_APP_KEY -cne 'vta_new' -or $script:AgentAppId -cne 'cursor') {
    throw 'The same-identity key refresh failed'
}
Write-Output 'Get-AgentCredential checks passed'
