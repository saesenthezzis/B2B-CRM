@echo off
chcp 65001 >nul
echo ============================================
echo   Install 1C - Turso Sync Monitor
echo ============================================
echo.

set PYTHON_PATH=python
set SCRIPT_DIR=%~dp0
set SCRIPT_PATH=%SCRIPT_DIR%sync_daemon.py
set TASK_NAME=RMKO_AutoSync_Monitor

echo Checking Python...
%PYTHON_PATH% --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found! Install Python and add to PATH.
    pause
    exit /b 1
)
echo [OK] Python found.
echo.

echo Checking watchdog dependency...
%PYTHON_PATH% -c "import watchdog" >nul 2>&1
if errorlevel 1 (
    echo [WARNING] watchdog not installed. Installing...
    %PYTHON_PATH% -m pip install watchdog
    if errorlevel 1 (
        echo [ERROR] Failed to install watchdog.
        pause
        exit /b 1
    )
    echo [OK] watchdog installed.
) else (
    echo [OK] watchdog already installed.
)
echo.

echo Removing old task if exists...
schtasks /query /tn "%TASK_NAME%" >nul 2>&1
if not errorlevel 1 (
    schtasks /delete /tn "%TASK_NAME%" /f >nul 2>&1
)

echo Creating Windows Task Scheduler job...
echo   Task name:      %TASK_NAME%
echo   Mode:           Continuous monitoring
echo   Script:    %SCRIPT_PATH%
echo   Trigger:        System startup
echo.

schtasks /create ^
    /tn "%TASK_NAME%" ^
    /tr "\"%PYTHON_PATH%\" \"%SCRIPT_PATH%\" monitor" ^
    /sc onstart ^
    /ru SYSTEM ^
    /rl highest ^
    /f

if errorlevel 1 (
    echo.
    echo [ERROR] Failed to create task.
    echo Check admin rights and try again.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   [OK] Monitor installed successfully!
echo ============================================
echo.
echo Task "%TASK_NAME%" will run automatically at system startup.
echo.
echo To manage task open Task Scheduler (taskschd.msc)
echo and find task "%TASK_NAME%".
echo.
echo To remove task:
echo   schtasks /delete /tn "%TASK_NAME%" /f
echo.
echo For testing single sync:
echo   python sync_daemon.py once
echo.
pause
