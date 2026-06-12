$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Scripts = Join-Path $Root "team-reports\scripts"

Write-Host "Weekly rollup + git sync"
python (Join-Path $Scripts "aggregate_weekly.py") --date today --write-db
python (Join-Path $Scripts "git_sync.py") --message "chore(team-reports): weekly rollup"
Write-Host "Done."
