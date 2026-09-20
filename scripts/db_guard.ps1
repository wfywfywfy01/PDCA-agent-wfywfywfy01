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
  [int]$RestartCooldownMinutes = 30,
  [string]$WorkbenchUrl = 'http://127.0.0.1:8767/health',
  [int]$WorkbenchPort = 8767,
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
  # 两个坑：
  #   1) VPN 断开时企业网络设备仍会“完成”TCP 握手，端口看起来是通的，协议层却完全无响应；
  #   2) OpenVPN Connect 可能走 TAP(TUN_WIN) 通道，此时 DCO 网卡始终显示 Disconnected，
  #      而且断开后 TAP 网卡仍保留残留 IP 并保持 Up 状态。
  # 因此以 OpenVPN 客户端日志里最后一条 EVENT 为准，网卡状态只作为辅助信息。
  $adapters = Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object { $_.InterfaceDescription -match 'OpenVPN' }
  $names = '未检测到 OpenVPN 网卡'
  if ($adapters) { $names = ($adapters | ForEach-Object { $_.Name + '(' + $_.Status + ')' }) -join ', ' }

  $logPath = Join-Path $env:APPDATA 'OpenVPN Connect\log\ovpn.log'
  if (Test-Path $logPath) {
    $lastEvent = Get-Content $logPath -Tail 400 -ErrorAction SilentlyContinue |
      Select-String -Pattern 'EVENT: (CONNECTED|DISCONNECTED|RECONNECTING|AUTH_FAILED)' |
      Select-Object -Last 1
    if ($lastEvent) {
      $line = $lastEvent.Line
      $isUp = $line -match 'EVENT: CONNECTED'
      $stamp = ''
      $m = [regex]::Match($line, '\[(?<ts>[^\]]+)\]')
      if ($m.Success) { $stamp = $m.Groups['ts'].Value }
      $summary = '日志最后事件: '
      if ($isUp) { $summary = $summary + '已连接' } else { $summary = $summary + '未连接' }
      if ($stamp) { $summary = $summary + '（' + $stamp + '）' }
      return @{ Known = $true; Up = $isUp; Detail = $summary + ' | 网卡: ' + $names }
    }
  }

  if (-not $adapters) { return @{ Known = $false; Up = $true; Detail = $names } }
  $up = @($adapters | Where-Object { $_.Status -eq 'Up' })
  return @{ Known = $true; Up = ($up.Count -gt 0); Detail = '网卡: ' + $names }
}

function Test-WorkbenchAlive {
  # 返回 Ok/Detail/Responding：
  #   Responding=$true  说明进程活着但可能降级（HTTP 5xx）——不应盲目重启
  #   Responding=$false 说明进程没在应答（超时/拒绝）——才算需要重启的“卡死”
  try {
    $r = Invoke-WebRequest -Uri $WorkbenchUrl -UseBasicParsing -TimeoutSec 12
    return @{ Ok = ($r.StatusCode -eq 200); Detail = 'HTTP ' + $r.StatusCode; Responding = $true }
  } catch {
    $code = $_.Exception.Response.StatusCode.value__
    if ($code) { return @{ Ok = $false; Detail = 'HTTP ' + $code; Responding = $true } }
    return @{ Ok = $false; Detail = 'unreachable'; Responding = $false }
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

function Stop-WorkbenchProcess {
  # 只在“进程无应答”时调用：找到监听端口的老进程并终止，避免新进程绑不上端口。
  $conn = Get-NetTCPConnection -LocalPort $WorkbenchPort -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $conn) { Write-GuardLog '端口无监听进程，直接启动'; return }
  try {
    taskkill /PID $conn.OwningProcess /F 2>&1 | Out-Null
    Write-GuardLog ('已终止无应答的工作台进程 PID ' + $conn.OwningProcess)
    Start-Sleep -Seconds 3
  } catch {
    Write-GuardLog ('终止进程失败: ' + $_.Exception.Message)
  }
}

function Start-Workbench {
  Write-GuardLog '尝试拉起工作台服务…'
  Start-Process cmd -ArgumentList '/c', 'start.bat' -WorkingDirectory $WorkbenchRoot -WindowStyle Hidden
  # 启动并轮询：数据库引导 + 迁移可能耗时，最多等 90 秒再判定
  for ($i = 1; $i -le 9; $i++) {
    Start-Sleep -Seconds 10
    $probe = Test-WorkbenchAlive
    if ($probe.Ok) { Write-GuardLog ('工作台启动成功（约 ' + ($i * 10) + ' 秒）'); return $probe }
  }
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

# 工作台异常处置：区分“进程无应答（需重启）”与“进程降级（5xx，不重启）”，并加重启冷却
$lastRestartAt = [datetime]::MinValue
if ($state.lastRestartAt) { try { $lastRestartAt = [datetime]::Parse($state.lastRestartAt) } catch { } }
$restartCooldownOk = ((Get-Date) - $lastRestartAt).TotalMinutes -ge $RestartCooldownMinutes

if ($dbState -eq 'up' -and $wbState -eq 'down' -and $upStreak -ge $RecoverStreakRequired) {
  if (-not $wb.Responding) {
    # 宽限期复检：手工部署/重启会造成短暂“无应答”窗口；
    # 此时贸然杀进程或再拉一个实例，会打断正在进行中的部署。
    Start-Sleep -Seconds 20
    $recheck = Test-WorkbenchAlive
    if ($recheck.Ok) {
      Write-GuardLog ('复检时工作台已恢复（' + $recheck.Detail + '），可能正在部署/重启，本次不干预')
      $wbState = 'up'
    } elseif ($restartCooldownOk) {
      Stop-WorkbenchProcess
      $after = Start-Workbench
      $lastRestartAt = Get-Date
      if ($after.Ok) {
        Send-Alert '工作台已自动恢复' ('数据库可用，工作台进程无应答，已自动重启成功（' + $after.Detail + '）。')
      } else {
        Send-Alert '工作台自动恢复失败' ('数据库可用但工作台仍不可访问（' + $after.Detail + '），已尝试重启一次，需要人工介入。')
      }
      if ($after.Ok) { $wbState = 'up' } else { $wbState = 'down' }
      $alerted = $true
    } else {
      Write-GuardLog ('工作台无应答，但距上次自动重启不足 ' + $RestartCooldownMinutes + ' 分钟，本次不重启（避免反复重启）')
    }
  } else {
    # 进程有响应但非 200：可能仍在恢复或降级，自动重启只会打断它
    Write-GuardLog ('工作台有响应但非 200（' + $wb.Detail + '），不自动重启')
    if ($state.workbench -ne 'down') {
      $sent = Send-Alert '工作台健康检查异常' ('数据库正常，但 /health 返回 ' + $wb.Detail + '。进程存活，守护不会自动重启；请查看 pdca_workbench 日志确认原因。')
      if ($sent) { $alerted = $true }
    }
  }
}

$newState = @{
  db = $dbState
  workbench = $wbState
  checkedAt = (Get-Date).ToString('o')
  lastAlertAt = $state.lastAlertAt
  lastRestartAt = if ($lastRestartAt -gt [datetime]::MinValue) { $lastRestartAt.ToString('o') } else { '' }
  lastDownAlertAt = if ($lastDownAlertAt -gt [datetime]::MinValue) { $lastDownAlertAt.ToString('o') } else { '' }
  downStreak = $downStreak
  upStreak = $upStreak
}
if ($alerted) { $newState.lastAlertAt = (Get-Date).ToString('o') }
if (-not (Test-Path $stateDir)) { New-Item -ItemType Directory -Force -Path $stateDir | Out-Null }
$newState | ConvertTo-Json | Set-Content -Path $stateFile -Encoding UTF8
