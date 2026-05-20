@echo off
REM ============================================================
REM TradingAgents -- install script (Windows)
REM
REM Sets up the Python environment ONCE. After this finishes,
REM use start.bat to launch the GUI -- no reinstall needed.
REM
REM Re-run this script any time you pull updates or change deps.
REM ============================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

REM ---- 1. Locate Python --------------------------------------------------
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    set "PY=py -3"
) else (
    where python >nul 2>nul
    if !ERRORLEVEL! EQU 0 (
        set "PY=python"
    ) else (
        echo.
        echo  [X] Python 3.10+ was not found on your PATH.
        echo      Download it from https://www.python.org/downloads/ and try again.
        echo      Be sure to check "Add Python to PATH" during install.
        echo.
        pause
        exit /b 1
    )
)

REM ---- 2. Version check --------------------------------------------------
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"
if !ERRORLEVEL! NEQ 0 (
    echo  [X] Python 3.10 or newer is required.
    %PY% --version
    pause
    exit /b 1
)

REM ---- 3. Create the venv ------------------------------------------------
if exist ".venv\Scripts\python.exe" (
    echo  [i] Existing virtual environment detected at .venv\
    set /p REINSTALL="    Reinstall from scratch? [y/N] "
    if /i "!REINSTALL!"=="y" (
        echo  [*] Removing existing .venv ...
        rmdir /s /q ".venv"
        %PY% -m venv .venv
    )
) else (
    echo  [*] Creating virtual environment in .venv ...
    %PY% -m venv .venv
)

if not exist ".venv\Scripts\python.exe" (
    echo  [X] Virtual environment creation failed.
    pause
    exit /b 1
)
set "VPY=.venv\Scripts\python.exe"

REM ---- 4. Install dependencies -------------------------------------------
echo.
echo  [*] Upgrading pip ...
"%VPY%" -m pip install --upgrade pip --quiet

echo  [*] Installing TradingAgents and GUI dependencies ^(this may take a minute^) ...
"%VPY%" -m pip install -e ".[gui]"
if !ERRORLEVEL! NEQ 0 (
    echo.
    echo  [X] Dependency install failed. Scroll up for the error.
    pause
    exit /b 1
)

REM ---- 5. Record success -------------------------------------------------
for /f "skip=1 tokens=*" %%h in ('certutil -hashfile pyproject.toml SHA1 ^| findstr /v ":"') do (
    if not defined PYPROJECT_HASH set "PYPROJECT_HASH=%%h"
)
> ".venv\.deps-installed.txt" echo !PYPROJECT_HASH!

echo.
echo  ============================================================
echo   Install complete. To launch the GUI, run:
echo.
echo       start.bat
echo.
echo   Or directly:
echo.
echo       .venv\Scripts\python.exe -m gui.app
echo  ============================================================
echo.
pause
