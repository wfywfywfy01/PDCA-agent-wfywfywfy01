$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$RepoSkill = Join-Path $RepoRoot ".cursor\skills\cursor-daily-report"
$Target = Join-Path $env:USERPROFILE ".cursor\skills\cursor-daily-report"

if (-not (Test-Path $RepoSkill)) {
    throw "Skill not found: $RepoSkill"
}

New-Item -ItemType Directory -Force -Path $Target | Out-Null
Copy-Item -Path (Join-Path $RepoSkill "*") -Destination $Target -Recurse -Force
Write-Host "Skill installed to: $Target"
