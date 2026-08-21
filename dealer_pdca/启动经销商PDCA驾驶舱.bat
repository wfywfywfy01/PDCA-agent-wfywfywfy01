@echo off
chcp 65001 >nul
set "ROOT=%~dp0"
set "PYTHON=C:\Users\frank\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"
echo 经销商 PDCA 驾驶舱 v1 — http://127.0.0.1:8766
echo 关闭本窗口即停止服务。
"%PYTHON%" "%ROOT%api\server.py"
pause
