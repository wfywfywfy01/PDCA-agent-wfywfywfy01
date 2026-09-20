<#
.SYNOPSIS
  PDCA 数据库与工作台守护：故障即时告警，恢复后自动拉起服务。

.DESCRIPTION
  由计划任务每 5 分钟调用一次。检查内容：
    1) 生产 PostgreSQL 协议层是否可用（TCP 通但服务卡死也算不可用）；
    2) 工作台 /health 是否正常；
    3) 数据库不可用 -> IM 告警（仅状态变化时发送，避免刷屏）；
    4) 数据库恢复但工作台未起来 -> 自动重启工作台并复验。
  状态记录：pdca-workbench/data/runtime/db_guard_state.json
#>
[CmdletBinding()]
param(
  [string]$WorkbenchRoot = 'D:\经销商PDCA\pdca-workbench',
  [string]$PythonExe = 'D:\Python\python.exe',
  [string]$AlertBotAppId = 'vbot_RsnvScIUYM9n84FS',
  [string]$AlertUserId = '13365',
  [switch]$Quiet
)

$ErrorActionPreference = 'Continue'
$NL = [Environment]::NewLine
$envFile = Join-Path $WorkbenchRoot '.env'
$stateDir = Join-Path $WorkbenchRoot 'data\runtime'
$stateFile = Join-Path $stateDir 'db_guard_state.json'
$logDir = Join-Path $WorkbenchRoot 'data\logs'

function Write-GuardLog([string]$message) {
  $stamp = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
  $line = $stamp + ' | db_guard | ' + $message
  if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force -Path $logDir | Out-Null }
  Add-Content -Path (Join-Path $logDir 'db_guard.log') -Value $line -Encoding UTF8
  if (-not $Quiet) { Write-Host $line }
}

function Get-DbTarget {
  $url = ''
  if (Test-Path $envFile) {
    $match = Select-String -Path $envFile -Pattern '^PDCA_DATABASE_URL=(.+)$' | Select-Object -First 1
    if ($match) { $url = $match.Matches[0].Groups[1].Value.Trim() }
  }
  if (-not $url) { return $null }
  $m = [regex]::Match($url, '://(?<user>[^:]+):(?<pass>[^@]+)@(?<host>[^:/]+):?(?<port>[0-9]*)/(?<db>[^?]+)')
  if (-not $m.Success) { return $null }
  $port = 5432
  if ($m.Groups['port'].Value) { $port = [int]$m.Groups['port'].Value }
  return @{
    Host = $m.Groups['host'].Value
    Port = $port
    User = $m.Groups['user'].Value
    Password = $m.Groups['pass'].Value
    Database = $m.Groups['db'].Value
  }
}

function Test-DbAlive($target) {
  $code = @'
import sys
import psycopg2
host, port, user, password, database = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5]
try:
    conn = psycopg2.connect(host=host, port=port, user=user, password=password, dbname=database, connect_timeout=5)
    cur = conn.cursor()
    cur.execute('select 1')
    cur.fetchone()
    conn.close()
    print('OK')
except Exception as exc:
    print('FAIL ' + type(exc).__name__ + ': ' + str(exc)[:180])
'@
  if (-not (Test-Path $stateDir)) { New-Item -ItemType Directory -Force -Path $stateDir | Out-Null }
  $tmp = Join-Path $stateDir 'db_probe.py'
  Set-Content -Path $tmp -Value $code -Encoding UTF8
  $out = (& $PythonExe $tmp $target.Host $target.Port $target.User $target.Password $target.Database 2>&1) -join ' '
  $text = $out.Trim()
  return @{ Ok = $text.StartsWith('OK'); Detail = $text }
}

function Test-WorkbenchAlive {
  try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8767/health' -UseBasicParsing -TimeoutSec 12
    return @{ Ok = ($r.StatusCode -eq 200); Detail = 'HTTP ' + $r.StatusCode }
  } catch {
    $code = $_.Exception.Response.StatusCode.value__
    if ($code) { return @{ Ok = $false; Detail = 'HTTP ' + $code } }
    return @{ Ok = $false; Detail = 'unreachable' }
  }
}

function Send-Alert([string]$title, [string]$body) {
  $message = '[PDCA 守护] ' + $title + $NL + $body
  try {
    $out = (& vertu-cli im +bot-send-user --app-id $AlertBotAppId --user-id $AlertUserId --body $message 2>&1) -join ' '
    $short = $out.Trim()
    if ($short.Length -gt 120) { $short = $short.Substring(0, 120) }
    Write-GuardLog ('IM 告警已发送: ' + $short)
  } catch {
    Write-GuardLog ('IM 告警发送失败: ' + $_.Exception.Message)
  }
}

function Start-Workbench {
  Write-GuardLog '尝试拉起工作台服务…'
  Start-Process cmd -ArgumentList '/c', 'start.bat' -WorkingDirectory $WorkbenchRoot -WindowStyle Hidden
  Start-Sleep -Seconds 20
  return Test-WorkbenchAlive
}

# ── 主流程 ───────────────────────────────────────────────────────────────
$target = Get-DbTarget
if (-not $target) { Write-GuardLog '无法解析 PDCA_DATABASE_URL，跳过'; exit 0 }

$state = @{ db = 'unknown'; workbench = 'unknown'; lastAlertAt = '' }
if (Test-Path $stateFile) {
  try { $state = Get-Content $stateFile -Raw | ConvertFrom-Json } catch { }
}

$db = Test-DbAlive $target
$wb = Test-WorkbenchAlive
$dbState = 'down'
if ($db.Ok) { $dbState = 'up' }
$wbState = 'down'
if ($wb.Ok) { $wbState = 'up' }
$previousDb = $state.db

Write-GuardLog ('db=' + $dbState + ' (' + $db.Detail + ')  workbench=' + $wbState + ' (' + $wb.Detail + ')')

$alerted = $false
if ($dbState -eq 'down' -and $previousDb -ne 'down') {
  Send-Alert '生产数据库不可用' ($target.Host + ':' + $target.Port + '/' + $target.Database + ' 探测失败：' + $db.Detail + $NL + '工作台状态：' + $wb.Detail + $NL + '请检查数据库主机（曾出现 TCP 可连但服务冻结的情况）。')
  $alerted = $true
}

if ($dbState -eq 'up' -and $previousDb -eq 'down') {
  Send-Alert '生产数据库已恢复' ($target.Host + ':' + $target.Port + ' 已可正常连接。工作台状态：' + $wb.Detail)
  $alerted = $true
}

if ($dbState -eq 'up' -and $wbState -eq 'down') {
  $after = Start-Workbench
  if ($after.Ok) {
    Send-Alert '工作台已自动恢复' ('数据库恢复后自动重启工作台成功（' + $after.Detail + '）。')
  } else {
    Send-Alert '工作台自动恢复失败' ('数据库可用但工作台仍不可访问（' + $after.Detail + '），需要人工介入。')
  }
  if ($after.Ok) { $wbState = 'up' } else { $wbState = 'down' }
  $alerted = $true
}

$newState = @{
  db = $dbState
  workbench = $wbState
  checkedAt = (Get-Date).ToString('o')
  lastAlertAt = $state.lastAlertAt
}
if ($alerted) { $newState.lastAlertAt = (Get-Date).ToString('o') }
if (-not (Test-Path $stateDir)) { New-Item -ItemType Directory -Force -Path $stateDir | Out-Null }
$newState | ConvertTo-Json | Set-Content -Path $stateFile -Encoding UTF8
