@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3 main.py
if errorlevel 1 (
 echo.
 echo R4启动失败，请检查 Python、PySide6 和原上位机设备依赖。
 pause
)
