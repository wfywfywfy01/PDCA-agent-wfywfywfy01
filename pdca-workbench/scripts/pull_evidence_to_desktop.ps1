# -*- coding: utf-8 -*-
<#
.SYNOPSIS
  把容器里当天生成的督战官产出物拉到本机「督战官文件」目录（固定测试流程的交付环节）。

.DESCRIPTION
  1) 默认取「昨天」作为数据日（08:00 出的是前一天的证据）；
  2) 优先从容器 data/exports/evidence 拉 HTML + JSON；
  3) 容器没有（任务失败/还没跑）时，退回本机现场跑 scripts/evidence_report.py；
  4) 顺带拉最新的 08:00 策略核查 HTML（容器 data/exports/strategy_wa）；
  5) 全过程写日志到 %LOCALAPPDATA%\PDCA\evidence-logs\。

.NOTES
  产出目录（2026-09-23 用户要求：督战官文件一律不准放桌面）：
    D:\Vertu\data\excel\26年数据\<月>月\部门工作画像\督战官文件
  可用 -DropDir 覆盖，或设环境变量 PDCA_DROP_DIR（支持 {month} 占位符）。
  ⚠ 本文件必须保存为 UTF-8 with BOM：Windows PowerShell 5.1 读无 BOM 的 UTF-8 会按
    ANSI(GBK) 解码，中文路径变乱码 -> docker cp 找不到文件（2026-09-23 实测踩坑）。
  文件名保留 *_to_desktop 是历史原因（计划任务指向它），行为已改为写上面的目录。
  需要 DOCKER_HOST（默认读环境变量 PDCA_DOCKER_HOST，最后退回 tcp://10.100.0.176:2375）。
#>
[CmdletBinding()]
param(
    [string]$Day = "",
    [string]$DropDir = "",
    [string]$DockerHost = "",
    [int]$Images = 24
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$workbench = Join-Path $repoRoot "pdca-workbench"
if (-not (Test-Path $workbench)) { $workbench = $repoRoot }
$logDir = Join-Path $env:LOCALAPPDATA "PDCA\evidence-logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logPath = Join-Path $logDir ("evidence-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".log")
function Write-Log([string]$Message) {
    $line = (Get-Date -Format "yyyy-MM-dd HH:mm:ss") + " " + $Message
    Write-Host $line
    Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
}

function Resolve-DropDir([string]$Explicit) {
    # 注意 1：-Format "M" 是「月日」标准格式（9月23日），不是月份数字
    # 注意 2：必须转成 string，否则 Int32 + "月..." 会按数字相加报 FormatException
    $month = (Get-Date).Month.ToString()
    if ($Explicit) { return ($Explicit -replace "\{month\}", $month) }
    if ($env:PDCA_DROP_DIR) { return ($env:PDCA_DROP_DIR -replace "\{month\}", $month) }
    $root = "D:\Vertu\data\excel\26年数据"
    return (Join-Path $root ($month + "月\部门工作画像\督战官文件"))
}

if (-not $Day) { $Day = (Get-Date).AddDays(-1).ToString("yyyy-MM-dd") }
$drop = Resolve-DropDir $DropDir
New-Item -ItemType Directory -Force -Path $drop | Out-Null
if (-not $DockerHost) {
    $DockerHost = $env:PDCA_DOCKER_HOST
    if (-not $DockerHost) { $DockerHost = "tcp://10.100.0.176:2375" }
}
$env:DOCKER_HOST = $DockerHost
Write-Log ("target day=" + $Day + " docker=" + $DockerHost + " dropdir=" + $drop)

$html = Join-Path $drop ("督战证据_" + $Day + ".html")
$json = Join-Path $drop ("督战证据_" + $Day + ".json")
$containerHtml = "/app/data/exports/evidence/督战证据_" + $Day + ".html"

$pulled = $false
try {
    docker cp ("pdca-workbench:" + $containerHtml) $html 2>$null | Out-Null
    if ((Test-Path $html) -and ((Get-Item $html).Length -gt 20000)) {
        docker cp ("pdca-workbench:/app/data/exports/evidence/督战证据_" + $Day + ".json") $json 2>$null | Out-Null
        $pulled = $true
        Write-Log ("pulled from container: " + [math]::Round((Get-Item $html).Length / 1KB) + " KB")
    } else {
        Write-Log "container evidence html missing or too small"
    }
} catch {
    Write-Log ("docker cp failed: " + $_.Exception.Message)
}

if (-not $pulled) {
    Write-Log "container copy unavailable -> running local generator"
    Push-Location $workbench
    try {
        $env:PYTHONIOENCODING = "utf-8"
        python "scripts/evidence_report.py" --day $Day --images $Images --out $html 2>&1 |
            ForEach-Object { Write-Log $_ }
    } finally {
        Pop-Location
    }
}

# 08:00 策略核查 HTML（容器 data/exports/strategy_wa/）
# 注意：不能靠 `docker exec ls` 回读中文文件名（计划任务上下文按 ANSI 解码 -> 乱码 -> cp 找不到），
# 这里直接用脚本内的中文常量拼容器路径（脚本带 BOM，解码正确）。
foreach ($d in @((Get-Date).ToString("yyyy-MM-dd"), (Get-Date).AddDays(-1).ToString("yyyy-MM-dd"))) {
    $name = "策略核查_" + $d + ".html"
    $src = "/app/data/exports/strategy_wa/" + $name
    $dst = Join-Path $drop $name
    docker exec pdca-workbench test -f $src 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Log ("strategy not in container (skip): " + $name); continue }
    try {
        docker cp ("pdca-workbench:" + $src) $dst 2>$null | Out-Null
        if (Test-Path $dst) { Write-Log ("strategy pulled: " + $dst) }
    } catch {
        Write-Log ("strategy pull failed: " + $_.Exception.Message)
    }
}

if (Test-Path $html) {
    Write-Log ("done: " + $html)
    exit 0
}
Write-Log "FAILED: no report produced"
exit 1
