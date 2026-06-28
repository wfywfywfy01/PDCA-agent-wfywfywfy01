# 注册每日 06:30 自动同步任务（vertu CLI → 云端 PostgreSQL）
# 以管理员权限运行：
#   powershell -ExecutionPolicy Bypass -File setup_daily_sync_task.ps1

param(
    [string]$PythonExe  = "",
    [string]$Workbench  = $PSScriptRoot | Split-Path -Parent,
    [string]$TaskName   = "PDCA-DailySync",
    [string]$RunHour    = "06",
    [string]$RunMinute  = "30"
)

# 自动查找 Python
if (-not $PythonExe) {
    foreach ($candidate in @("python", "python3", "py")) {
        $found = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($found) { $PythonExe = $found.Source; break }
    }
}
if (-not $PythonExe) {
    Write-Error "未找到 Python，请用 -PythonExe 指定路径"
    exit 1
}

$SyncScript = Join-Path $Workbench "scripts\sync_from_vertu.py"
if (-not (Test-Path $SyncScript)) {
    Write-Error "脚本不存在: $SyncScript"
    exit 1
}

$LogFile = Join-Path $Workbench "logs\pdca_sync.log"
New-Item -ItemType Directory -Force -Path (Split-Path $LogFile) | Out-Null

# 命令：python scripts/sync_from_vertu.py >> logs/pdca_sync.log 2>&1
$Action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "`"$SyncScript`"" `
    -WorkingDirectory $Workbench

$Trigger = New-ScheduledTaskTrigger -Daily -At "${RunHour}:${RunMinute}"

$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable

$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel Highest

# 注册（存在则更新）
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Set-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings
    Write-Output "已更新任务: $TaskName"
} else {
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal
    Write-Output "已注册任务: $TaskName"
}

Write-Output ""
Write-Output "  Python:   $PythonExe"
Write-Output "  脚本:     $SyncScript"
Write-Output "  工作目录: $Workbench"
Write-Output "  触发时间: 每天 ${RunHour}:${RunMinute}"
Write-Output "  日志:     $LogFile (手动重定向，请在脚本中配置)"
Write-Output ""
Write-Output "手动测试："
Write-Output "  python `"$SyncScript`" --only sellin"
