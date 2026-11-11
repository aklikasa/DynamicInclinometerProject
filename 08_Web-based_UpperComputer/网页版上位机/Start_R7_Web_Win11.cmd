@echo off
setlocal EnableExtensions DisableDelayedExpansion
title WK IMU R7 - Native Web - REAL PCB
set "APP_DIR=%~dp0TiltSensorCalibration"
if not exist "%APP_DIR%\native_web\server.py" goto MISSING
cd /d "%APP_DIR%"
if errorlevel 1 goto BADCD
if not exist ".venv_web\Scripts\python.exe" goto NO_VENV
echo ===============================================================
echo  WK IMU R7 WEB - No PySide6 desktop window - Real PCB
 echo  Open browser: http://127.0.0.1:8765/
echo  Keep this command window open. Do NOT start old R7 on same COM.
echo  Logs: TiltSensorCalibration\web_startup.log
 echo  2TD600: manual position + sequential dual-axis zero + software stop.
echo  ACC/GYRO: Guided + supervised auto flow; full auto locked until SITE commissioning.
echo  PLC write and WK motion NOT enabled.
echo ===============================================================
".venv_web\Scripts\python.exe" -u -m native_web.startup_win11
if errorlevel 1 echo [ERROR] Backend stopped unexpectedly. Read web_startup.log.
goto FINISH
:NO_VENV
echo [ERROR] Missing project Python environment.
echo Run Install_Web_Win11.cmd first.
goto FINISH
:MISSING
echo [ERROR] Did you extract the entire ZIP? Missing native_web\server.py.
goto FINISH
:BADCD
echo [ERROR] Cannot access project path. Try D:\WK_R7_WEB.
:FINISH
echo.
echo This window remains open so errors are visible.
pause
endlocal
