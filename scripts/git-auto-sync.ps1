$ErrorActionPreference = "Stop"

$message = "Auto Sync $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"

$status = git status --short
$status
$dangerous = $status | Where-Object {
    ($_ -match '(^|/)\.env(\.|$)') -or
    ($_ -match 'vemory_people\.local\.json') -or
    ($_ -match 'data_platform/data_role_pdca_mvp/(outputs|outbox|inputs)/')
}
if ($dangerous) {
    throw "Refusing to auto-commit secrets/generated business data: $dangerous"
}
git add .
git commit -m $message
git push

