@echo off
echo ============================================
echo   Install RMKO Sync Windows Service
echo ============================================
echo.

set PYTHON_PATH=python
set SCRIPT_DIR=%~dp0
set SCRIPT_PATH=%SCRIPT_DIR%sync_service.py
set SERVICE_NAME=RMKOSyncService

echo Checking Python...
%PYTHON_PATH% --version
if errorlevel 1 (
    echo [ERROR] Python not found! Install Python and add to PATH.
    pause
    exit /b 1
)
echo [OK] Python found.
echo.

echo Installing pywin32 dependency...
%PYTHON_PATH% -m pip install pywin32
if errorlevel 1 (
    echo [ERROR] Failed to install pywin32.
    pause
    exit /b 1
)
echo [OK] pywin32 installed.
echo.

echo Removing old service if exists...
%PYTHON_PATH% "%SCRIPT_PATH%" remove
echo.

echo Installing Windows Service...
%PYTHON_PATH% "%SCRIPT_PATH%" install
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to install service.
    echo Make sure you are running as Administrator.
    pause
    exit /b 1
)

echo.
echo Starting service...
%PYTHON_PATH% "%SCRIPT_PATH%" start
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to start service.
    echo Check Windows Event Viewer for details.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   [OK] Service installed and started!
echo ============================================
echo.
echo Service "%SERVICE_NAME%" is now running.
echo.
echo Service details:
echo   Name:      %SERVICE_NAME%
echo   Display:   RMKO Auto Sync 1C-Turso
echo   Type:      Windows Service
echo.
echo To manage service:
echo   - Open "services.msc" to view all services
echo   - Find "%SERVICE_NAME%" in the list
echo   - Stop/Start/Restart as needed
echo.
echo To remove service:
echo   python sync_service.py stop
echo   python sync_service.py remove
echo   or run: uninstall_sync_service.bat
echo.
echo Log file: %SCRIPT_DIR%sync.log
echo.
pause