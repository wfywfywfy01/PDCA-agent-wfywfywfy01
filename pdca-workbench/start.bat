@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PDCA_WORKBENCH_PORT=8767
set PDCA_HOST=0.0.0.0
set PDCA_MVP_ROOT=%~dp0..\data_platform\data_role_pdca_mvp
set PDCA_REPO_ROOT=%~dp0..
if not exist ".env" (
  echo 请先复制 .env.example 为 .env 并填写 PDCA_DATABASE_URL ^(PostgreSQL^)
  pause
  exit /b 1
)
python run.py
