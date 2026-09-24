@echo off
rem 启动独立版 Clippy 桌宠（优先用本目录 host\electron.exe，其次 VPS 自带的 Electron）
setlocal
set HERE=%~dp0
set HOST=%HERE%host\electron.exe
set VPSEXE=C:\Program Files\VPS\VPS.exe

rem 关键：清掉可能被注入的 ELECTRON_RUN_AS_NODE，否则 Electron 会以纯 Node 模式启动，
rem 表现就是“进程秒退、require('electron') 找不到模块、没有任何日志”
set ELECTRON_RUN_AS_NODE=

if not exist "%HERE%main.js" (
  echo [x] 找不到 main.js，请确认本文件与 main.js 在同一目录。
  pause
  exit /b 1
)

if not exist "%HERE%engine\agents\clippy\map.mjs" (
  echo [x] 引擎素材缺失: %HERE%engine\
  echo     请先运行: powershell -NoProfile -ExecutionPolicy Bypass -File "%HERE%setup_engine.ps1"
  pause
  exit /b 1
)

if exist "%HOST%" goto run_host
if exist "%VPSEXE%" goto run_vps

echo [x] 找不到 Electron 运行环境。
echo     期望: "%HOST%"
echo     或:   "%VPSEXE%"
pause
exit /b 1

:run_host
echo 启动 Clippy 桌宠... 日志: %HERE%data\pet.log
start "" "%HOST%" "%HERE%main.js" "--user-data-dir=%HERE%data\chromium"
exit /b 0

:run_vps
echo 启动 Clippy 桌宠（VPS 内核）... 日志: %HERE%data\pet.log
start "" "%VPSEXE%" "%HERE%main.js" "--user-data-dir=%HERE%data\chromium"
exit /b 0
