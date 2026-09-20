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
  [string]$VertuCli = 'C:\Users\frank\AppData\Roaming\vertu-im-desktop\personal-opencode\home\bin\vertu-cli.cmd',
  [int]$DownAlertCooldownMinutes = 30,
  [int]$RecoverStreakRequired = 2,
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

function Get-VpnState {
  # 远端数据库在内网，必须经 VPN（vpn-cd.vertu.cn）可达。
  # 注意：VPN 断开时企业网络设备仍会“完成”TCP 握手，端口看起来是通的，
  # 但协议层完全没有响应——必须单独检查 VPN 网卡状态才能给出可执行的结论。
  $adapters = Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object { $_.InterfaceDescription -match 'OpenVPN' }
  if (-not $adapters) { return @{ Known = $false; Up = $true; Detail = '未检测到 OpenVPN 网卡' } }
  $names = ($adapters | ForEach-Object { $_.Name + '(' + $_.Status + ')' }) -join ', '
  $dco = $adapters | Where-Object { $_.InterfaceDescription -match 'DCO' }
  if ($dco) { return @{ Known = $true; Up = ($dco.Status -eq 'Up'); Detail = $names } }
  $up = @($adapters | Where-Object { $_.Status -eq 'Up' })
  return @{ Known = $true; Up = ($up.Count -gt 0); Detail = $names }
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

function Resolve-VertuCli {
  # 计划任务的 PATH 与交互式 shell 不同，可能解析到旧版 npm 包（缺少 im +bot-send-user）；
  # 优先使用桌面端内置 CLI 的绝对路径。
  if ($VertuCli -and (Test-Path $VertuCli)) { return $VertuCli }
  $cmd = Get-Command vertu-cli -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  return ''
}

function Send-Alert([string]$title, [string]$body) {
  $message = '[PDCA 守护] ' + $title + $NL + $body
  $cli = Resolve-VertuCli
  if (-not $cli) {
    Write-GuardLog 'IM 告警失败：找不到 vertu-cli'
    return $false
  }
  try {
    $out = (& $cli im +bot-send-user --app-id $AlertBotAppId --user-id $AlertUserId --body $message 2>&1) -join ' '
    $short = $out.Trim()
    if ($short.Length -gt 140) { $short = $short.Substring(0, 140) }
    if ($short -match 'unknown command|not found|error:') {
      Write-GuardLog ('IM 告警可能失败: ' + $short)
      return $false
    }
    Write-GuardLog ('IM 告警已发送: ' + $short)
    return $true
  } catch {
    Write-GuardLog ('IM 告警发送失败: ' + $_.Exception.Message)
    return $false
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

$state = @{ db = 'unknown'; workbench = 'unknown'; lastAlertAt = ''; lastDownAlertAt = ''; downStreak = 0; upStreak = 0 }
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

# 抗抖动计数：数据库主机曾出现“通—断—通”反复，避免告警刷屏
$downStreak = [int]$state.downStreak
$upStreak = [int]$state.upStreak
if ($dbState -eq 'down') { $downStreak = $downStreak + 1; $upStreak = 0 } else { $upStreak = $upStreak + 1; $downStreak = 0 }

Write-GuardLog ('db=' + $dbState + ' (' + $db.Detail + ')  workbench=' + $wbState + ' (' + $wb.Detail + ')  streak(up=' + $upStreak + ',down=' + $downStreak + ')')

$alerted = $false
$lastDownAlertAt = [datetime]::MinValue
if ($state.lastDownAlertAt) { try { $lastDownAlertAt = [datetime]::Parse($state.lastDownAlertAt) } catch { } }
$cooldownOk = ((Get-Date) - $lastDownAlertAt).TotalMinutes -ge $DownAlertCooldownMinutes

$vpn = Get-VpnState
Write-GuardLog ('VPN: ' + $vpn.Detail)

if ($dbState -eq 'down' -and $previousDb -ne 'down' -and $cooldownOk) {
  $cause = '请检查数据库主机（' + $target.Host + '）是否存活。'
  if ($vpn.Known -and -not $vpn.Up) {
    $cause = '本机 VPN 未连通（' + $vpn.Detail + '），内网数据库因此不可达。' + $NL + '请先恢复 VPN（OpenVPN Connect -> 连接 vpn-cd.vertu.cn），再确认数据库。'
  }
  $sent = Send-Alert '生产数据库不可用' ($target.Host + ':' + $target.Port + '/' + $target.Database + ' 探测失败：' + $db.Detail + $NL + '工作台状态：' + $wb.Detail + $NL + $cause + $NL + '（同类告警 ' + $DownAlertCooldownMinutes + ' 分钟内不再重复）')
  if ($sent) { $lastDownAlertAt = Get-Date; $alerted = $true }
} elseif ($dbState -eq 'down' -and $previousDb -ne 'down') {
  Write-GuardLog ('数据库不可用，但处于告警冷却期（' + $DownAlertCooldownMinutes + ' 分钟），本次不推送')
}

# 恢复需连续 N 次正常才确认，避免“刚恢复又断”造成误报
if ($dbState -eq 'up' -and $previousDb -eq 'down') {
  if ($upStreak -ge $RecoverStreakRequired) {
    $sent = Send-Alert '生产数据库已恢复' ($target.Host + ':' + $target.Port + ' 连续 ' + $upStreak + ' 次探测正常。工作台状态：' + $wb.Detail)
    if ($sent) { $alerted = $true }
  } else {
    Write-GuardLog ('数据库已连通，等待连续 ' + $RecoverStreakRequired + ' 次正常后再确认恢复（当前 ' + $upStreak + ' 次）')
  }
}

if ($dbState -eq 'up' -and $wbState -eq 'down' -and $upStreak -ge $RecoverStreakRequired) {
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
  lastDownAlertAt = if ($lastDownAlertAt -gt [datetime]::MinValue) { $lastDownAlertAt.ToString('o') } else { '' }
  downStreak = $downStreak
  upStreak = $upStreak
}
if ($alerted) { $newState.lastAlertAt = (Get-Date).ToString('o') }
if (-not (Test-Path $stateDir)) { New-Item -ItemType Directory -Force -Path $stateDir | Out-Null }
$newState | ConvertTo-Json | Set-Content -Path $stateFile -Encoding UTF8
