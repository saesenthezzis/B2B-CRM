@echo off
echo ============================================
echo   Install RMKO Sync Schedule Task
echo ============================================
echo.

set PYTHON_PATH=python
set SCRIPT_DIR=%~dp0
set SCRIPT_PATH=%SCRIPT_DIR%sync_daemon.py
set TASK_NAME=RMKO_AutoSync_Schedule

echo Checking Python...
%PYTHON_PATH% --version
if errorlevel 1 (
    echo [ERROR] Python not found! Install Python and add to PATH.
    pause
    exit /b 1
)
echo [OK] Python found.
echo.

echo Checking watchdog dependency...
%PYTHON_PATH% -c "import watchdog"
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

echo Removing old tasks if exist...
schtasks /query /tn "%TASK_NAME%" >nul 2>&1
if not errorlevel 1 (
    schtasks /delete /tn "%TASK_NAME%" /f
)
schtasks /query /tn "RMKO_AutoSync_Monitor" >nul 2>&1
if not errorlevel 1 (
    schtasks /delete /tn "RMKO_AutoSync_Monitor" /f
)

echo Creating scheduled task...
echo   Task name:      %TASK_NAME%
echo   Mode:           Every 30 minutes
echo   Script:    %SCRIPT_PATH%
echo   Trigger:        At system startup + repeat every 30 min
echo.

schtasks /create ^
    /tn "%TASK_NAME%" ^
    /tr "\"%PYTHON_PATH%\" \"%SCRIPT_PATH%\" once" ^
    /sc daily ^
    /st 00:00 ^
    /mo 1 ^
    /ri 30 ^
    /du 24:00 ^
    /ru "%USERNAME%" ^
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
echo   [OK] Schedule task installed successfully!
echo ============================================
echo.
echo Task "%TASK_NAME%" will run:
echo   - At system startup
echo   - Then every 30 minutes (24/7)
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