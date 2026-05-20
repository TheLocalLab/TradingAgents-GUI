@echo off
REM ============================================================
REM TradingAgents -- start script (Windows)
REM
REM Just launches the GUI. If install.bat hasn't been run yet
REM (no .venv), prints a clear error and exits -- does NOT auto-install.
REM
REM Pass any extra args (--host, --port, etc.) and they're forwarded
REM to the GUI: e.g.  start.bat --port 5555
REM ============================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

REM ---- 1. Check that install has been run --------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo  [X] No virtual environment found at .venv\
    echo.
    echo      Run install.bat first to set up dependencies.
    echo      You only need to install once.
    echo.
    pause
    exit /b 1
)

if not exist ".venv\.deps-installed.txt" (
    echo.
    echo  [!] Install marker missing -- dependencies may not be set up.
    echo      Run install.bat to re-install.
    echo.
    pause
    exit /b 1
)

REM Warn ^(but don't fail^) if pyproject.toml has changed since install.
for /f "skip=1 tokens=*" %%h in ('certutil -hashfile pyproject.toml SHA1 ^| findstr /v ":"') do (
    if not defined CURR_HASH set "CURR_HASH=%%h"
)
set /p OLD_HASH=<".venv\.deps-installed.txt"
if not "!CURR_HASH!"=="!OLD_HASH!" (
    echo.
    echo  [!] pyproject.toml has changed since install.
    echo      You may want to re-run install.bat to pick up new dependencies.
    echo      Continuing anyway in 3 seconds...
    timeout /t 3 /nobreak >nul
)

REM ---- 2. Launch ----------------------------------------------------------
set "VPY=.venv\Scripts\python.exe"
echo.
echo  [+] Starting TradingAgents GUI...
echo      Open in your browser:  http://127.0.0.1:5000
echo      Press Ctrl-C in this window to stop.
echo.

"%VPY%" -m gui.app %*
set "EXITCODE=%ERRORLEVEL%"

echo.
echo ============================================================
echo  Server exited with code %EXITCODE%.
echo ============================================================
echo.
pause
exit /b %EXITCODE%
