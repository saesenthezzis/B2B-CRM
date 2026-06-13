@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Обновление данных из xlsx-выгрузки...
echo (файл: "..\Рабочее место Корпоративного отдела .xlsx")
python core.py
echo.
echo Готово. Если РМКО открыто в браузере — нажмите F5.
pause
