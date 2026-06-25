@echo off
chcp 65001 >nul
echo ============================================
echo   Uninstall RMKO Sync Windows Service
echo ============================================
echo.

set PYTHON_PATH=python
set SCRIPT_DIR=%~dp0
set SCRIPT_PATH=%SCRIPT_DIR%sync_service.py
set SERVICE_NAME=RMKOSyncService

echo Stopping service...
%PYTHON_PATH% "%SCRIPT_PATH%" stop
if errorlevel 1 (
    echo [WARNING] Failed to stop service or service not running.
) else (
    echo [OK] Service stopped.
)
echo.

echo Removing service...
%PYTHON_PATH% "%SCRIPT_PATH%" remove
if errorlevel 1 (
    echo [ERROR] Failed to remove service.
    echo Make sure you are running as Administrator.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   [OK] Service removed successfully!
echo ============================================
echo.
echo Service "%SERVICE_NAME%" has been removed.
echo.
pause