@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   РМКО — рабочее место корпоративного отдела
echo   После запуска откройте: http://localhost:8000
echo   Коллеги по сети:        http://%COMPUTERNAME%:8000
echo   Не закрывайте это окно, пока работает РМКО.
echo ============================================
start "" http://localhost:8000
python app.py
pause
