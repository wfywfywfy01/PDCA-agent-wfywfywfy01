# -*- coding: utf-8 -*-
<#
.SYNOPSIS
  把容器里当天生成的「督战证据日报」拉到桌面（固定测试流程的交付环节）。

.DESCRIPTION
  1) 默认取「昨天」作为数据日（08:00 出的是前一天的证据）；
  2) 优先从容器 data/exports/evidence 拉 HTML + JSON；
  3) 容器没有（任务失败/还没跑）时，退回本机现场跑 scripts/evidence_report.py；
  4) 全过程写日志到 %LOCALAPPDATA%\PDCA\evidence-logs\。

.NOTES
  需要 DOCKER_HOST（默认读环境变量 PDCA_DOCKER_HOST，最后退回 tcp://10.100.0.176:2375）。
#>
[CmdletBinding()]
param(
    [string]$Day = "",
    [string]$Desktop = "",   # 留空则自动探测（非交互/服务上下文下 GetFolderPath 可能返回空）
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

if (-not $Day) { $Day = (Get-Date).AddDays(-1).ToString("yyyy-MM-dd") }
if (-not $Desktop) {
    $Desktop = [Environment]::GetFolderPath("Desktop")
}
if (-not $Desktop) { $Desktop = Join-Path $env:USERPROFILE "Desktop" }
if (-not (Test-Path $Desktop)) { $Desktop = Join-Path ("C:\Users\" + $env:USERNAME) "Desktop" }
if (-not (Test-Path $Desktop)) { $Desktop = "C:\Users\frank\Desktop" }
if (-not (Test-Path $Desktop)) { $Desktop = $env:TEMP }
if (-not $DockerHost) {
    $DockerHost = $env:PDCA_DOCKER_HOST
    if (-not $DockerHost) { $DockerHost = "tcp://10.100.0.176:2375" }
}
$env:DOCKER_HOST = $DockerHost
Write-Log ("target day=" + $Day + " docker=" + $DockerHost + " desktop=" + $Desktop)

$html = Join-Path $Desktop ("督战证据_" + $Day + ".html")
$json = Join-Path $Desktop ("督战证据_" + $Day + ".json")
$containerHtml = "/app/data/exports/evidence/督战证据_" + $Day + ".html"

$pulled = $false
try {
    docker cp ("pdca-workbench:" + $containerHtml) $html 2>$null | Out-Null
    if ((Test-Path $html) -and ((Get-Item $html).Length -gt 20000)) {
        docker cp ("pdca-workbench:/app/data/exports/evidence/督战证据_" + $Day + ".json") $json 2>$null | Out-Null
        $pulled = $true
        Write-Log ("pulled from container: " + [math]::Round((Get-Item $html).Length / 1KB) + " KB")
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

# 腕表闪购 WhatsApp 核查（08:00 出，若容器已生成就一并拉到桌面）
$campaignName = "机械腕表闪购_WhatsApp核查_" + $Day + ".html"
$campaignSrc = "/app/data/exports/campaign_wa/" + $campaignName
$campaignDst = Join-Path $Desktop $campaignName
try {
    docker cp ("pdca-workbench:" + $campaignSrc) $campaignDst 2>$null | Out-Null
    if (Test-Path $campaignDst) {
        Write-Log ("campaign pulled: " + $campaignDst)
    }
} catch {
    Write-Log ("campaign pull skipped: " + $_.Exception.Message)
}

if (Test-Path $html) {
    Write-Log ("done: " + $html)
    exit 0
}
Write-Log "FAILED: no report produced"
exit 1
