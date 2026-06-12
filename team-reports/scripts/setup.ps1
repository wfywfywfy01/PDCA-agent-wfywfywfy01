# -*- coding: utf-8 -*-
"""Windows 一键初始化团队日报环境。"""

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$TeamReports = Join-Path $Root "team-reports"
$EnvFile = Join-Path $TeamReports ".env"
$EnvExample = Join-Path $TeamReports ".env.example"
$UserFile = Join-Path $TeamReports "config/user.json"
$UserExample = Join-Path $TeamReports "config/user.example.json"

Write-Host "== Cursor 团队日报初始化 =="

if (-not (Test-Path $EnvFile)) {
    Copy-Item $EnvExample $EnvFile
    Write-Host "已创建 $EnvFile ，请填写 DB_PASSWORD 和 CURSOR_REPORT_USER"
} else {
    Write-Host ".env 已存在，跳过"
}

if (-not (Test-Path $UserFile)) {
    Copy-Item $UserExample $UserFile
    Write-Host "已创建 $UserFile ，请填写 username"
} else {
    Write-Host "user.json 已存在，跳过"
}

pip install -r (Join-Path $TeamReports "requirements.txt")
python (Join-Path $TeamReports "scripts/db_schema.py") --create-db

Write-Host "初始化完成。测试命令："
Write-Host "python team-reports/scripts/publish_daily.py --date today --skip-db"
