@echo off
rem 自检：启动桌宠约 12 秒后自动截图并退出，用来确认引擎/窗口/渲染都正常
setlocal
set HERE=%~dp0
set HOST=%HERE%host\electron.exe
set VPSEXE=C:\Program Files\VPS\VPS.exe
set ELECTRON_RUN_AS_NODE=

if exist "%HOST%" goto run_host
if exist "%VPSEXE%" goto run_vps
echo [x] 找不到 Electron 运行环境。
exit /b 1

:run_host
echo 自检启动中（约 12 秒后自动退出）...
echo 结果: %HERE%data\pet.log 和 %HERE%data\smoke-shot.png
start /wait "" "%HOST%" "%HERE%main.js" "--smoke" "--user-data-dir=%HERE%data\chromium-smoke"
goto done

:run_vps
echo 自检启动中（VPS 内核，约 12 秒后自动退出）...
start /wait "" "%VPSEXE%" "%HERE%main.js" "--smoke" "--user-data-dir=%HERE%data\chromium-smoke"
goto done

:done
echo.
echo 自检结束。结果: data\pet.log / data\smoke-shot.png
exit /b 0
