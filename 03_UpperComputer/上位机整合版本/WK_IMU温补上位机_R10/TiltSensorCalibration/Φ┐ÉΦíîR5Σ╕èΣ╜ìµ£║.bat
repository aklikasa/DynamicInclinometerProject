@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
    py -3 main.py
) else (
    python main.py
)
if errorlevel 1 (
    echo.
    echo 上位机启动失败；请检查Python、PySide6、Snap7、DLL与设备驱动。
    pause
)
