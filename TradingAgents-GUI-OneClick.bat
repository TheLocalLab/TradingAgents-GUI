@echo off
setlocal enabledelayedexpansion

REM ============================================================================
REM  TradingAgents-GUI — One-click Windows installer
REM  ----------------------------------------------------------------------------
REM  Installs Git (if missing), Miniconda + Python 3.11 (portable, no admin),
REM  clones the repo, installs all GUI deps, and drops a start_WebUI.bat
REM  next to this script. Safe to re-run — every step is skip-if-exists.
REM ============================================================================

set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"

echo.
echo =========================================
echo  TradingAgents-GUI - One-Click Installer
echo =========================================
echo.

REM ----- 1. Git (portable user install if missing) ------------------------------
where git >nul 2>nul
if errorlevel 1 (
    echo [1/5] Git not found. Downloading portable Git...
    set "GIT_INSTALLER=Git-setup.exe"
    REM Pin to a known-good version. Bump this when you want a newer Git.
    curl -L -k -o "!GIT_INSTALLER!" ^
        https://github.com/git-for-windows/git/releases/download/v2.47.1.windows.1/Git-2.47.1-64-bit.exe
    if errorlevel 1 (
        echo  [X] Download failed. Check your internet connection.
        goto end
    )
    echo      Installing Git silently to %USERPROFILE%\Git...
    start /wait "" "!GIT_INSTALLER!" /VERYSILENT /NORESTART /NOCANCEL /DIR="%USERPROFILE%\Git"
    if errorlevel 1 (
        echo  [X] Git install failed.
        goto end
    )
    del "!GIT_INSTALLER!"
    set "PATH=%USERPROFILE%\Git\cmd;%PATH%"
) else (
    echo [1/5] Git already installed.
)
git --version

REM ----- 2. Miniconda (portable, this folder) ----------------------------------
if not exist "%PROJECT_DIR%miniconda3\Scripts\activate.bat" (
    echo [2/5] Downloading Miniconda installer...
    curl -L -k -o miniconda.exe ^
        https://repo.anaconda.com/miniconda/Miniconda3-py311_24.7.1-0-Windows-x86_64.exe
    if errorlevel 1 (
        echo  [X] Miniconda download failed.
        goto end
    )
    echo      Installing Miniconda to %PROJECT_DIR%miniconda3...
    start /wait "" miniconda.exe /InstallationType=JustMe /RegisterPython=0 /S /D=%PROJECT_DIR%miniconda3
    if errorlevel 1 (
        echo  [X] Miniconda install failed.
        goto end
    )
    del miniconda.exe
) else (
    echo [2/5] Miniconda already installed.
)

set "CONDA_ROOT=%PROJECT_DIR%miniconda3"
set "PATH=%CONDA_ROOT%;%CONDA_ROOT%\Scripts;%CONDA_ROOT%\Library\bin;%PATH%"
call "%CONDA_ROOT%\Scripts\activate.bat"
if errorlevel 1 (
    echo  [X] Could not activate Miniconda base.
    goto end
)

REM Accept ToS so future conda commands don't prompt.
call conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main   >nul 2>nul
call conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r      >nul 2>nul
call conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/msys2  >nul 2>nul
call conda config --set plugins.auto_accept_tos yes >nul 2>nul

REM ----- 3. Conda environment 'TradingAgents-GUI' ------------------------------
call conda env list | findstr /B /C:"TradingAgents-GUI " >nul 2>nul
if errorlevel 1 (
    echo [3/5] Creating conda env 'TradingAgents-GUI' with Python 3.11...
    call conda create -y -n TradingAgents-GUI python=3.11
    if errorlevel 1 (
        echo  [X] Could not create conda environment.
        goto end
    )
) else (
    echo [3/5] Conda env 'TradingAgents-GUI' already exists.
)
call conda activate TradingAgents-GUI
if errorlevel 1 (
    echo  [X] Could not activate conda environment.
    goto end
)

REM ----- 4. Clone repo + install deps ------------------------------------------
if not exist "%PROJECT_DIR%TradingAgents-GUI\.git" (
    echo [4/5] Cloning TheLocalLab/TradingAgents-GUI...
    git clone https://github.com/TheLocalLab/TradingAgents-GUI.git "%PROJECT_DIR%TradingAgents-GUI"
    if errorlevel 1 (
        echo  [X] Git clone failed.
        goto end
    )
) else (
    echo [4/5] Repo already present - pulling latest...
    pushd "%PROJECT_DIR%TradingAgents-GUI"
    git pull --ff-only
    popd
)

cd /d "%PROJECT_DIR%TradingAgents-GUI"
echo      Installing TradingAgents + GUI dependencies (pip install -e)...
python -m pip install --upgrade pip
python -m pip install -e ".[gui]"
if errorlevel 1 (
    echo  [X] pip install failed.
    goto end
)

REM ----- 5. Drop start_WebUI.bat in PROJECT_DIR -------------------------------
echo [5/5] Creating start_WebUI.bat launcher...
(
echo @echo off
echo setlocal
echo set "BASE_DIR=%%~dp0"
echo set "CONDA_ROOT=%%BASE_DIR%%miniconda3"
echo set "PATH=%%CONDA_ROOT%%;%%CONDA_ROOT%%\Scripts;%%CONDA_ROOT%%\Library\bin;%%PATH%%"
echo call "%%CONDA_ROOT%%\Scripts\activate.bat"
echo call conda activate TradingAgents-GUI
echo cd /d "%%BASE_DIR%%TradingAgents-GUI"
echo echo =========================================
echo echo  TradingAgents GUI - Windows Launcher
echo echo =========================================
echo python -m gui.app
echo echo.
echo echo Process exited with code: %%errorlevel%%
echo pause
echo endlocal
) > "%PROJECT_DIR%start_WebUI.bat"

echo.
echo =========================================
echo  Install complete.
echo.
echo  Launch the GUI:   start_WebUI.bat   (next to this installer)
echo  Repo lives in:    %PROJECT_DIR%TradingAgents-GUI
echo  Conda env name:   TradingAgents-GUI
echo  Python:           3.11 (bundled in %PROJECT_DIR%miniconda3)
echo =========================================
echo.
goto done

:end
echo.
echo [!] Install aborted. See messages above.
echo.
pause
exit /b 1

:done
pause
endlocal
exit /b 0
