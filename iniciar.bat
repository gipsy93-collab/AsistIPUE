@echo off
title IPUE Granada - Control de Asistencia y Visor de Cumpleanos
cd /d "%~dp0"
echo =========================================================
echo   IPUE GRANADA - CONTROL DE ASISTENCIA Y CUMPLEANOS
echo =========================================================
echo.
echo Iniciando servidor local en http://localhost:5050...
start http://localhost:5050
python api\index.py
pause
