@echo off
setlocal EnableExtensions DisableDelayedExpansion
title WK IMU R7 - Windows COM Scan (Read Only)
set "APP_DIR=%~dp0TiltSensorCalibration"
cd /d "%APP_DIR%"
if errorlevel 1 goto BADCD
if not exist ".venv_web\Scripts\python.exe" goto MISSING
".venv_web\Scripts\python.exe" -m native_web.scan_com_win11
if errorlevel 1 echo [ERROR] Scan failed. Check Install_Web_Win11.cmd.
goto END
:MISSING
echo [ERROR] Web Python environment missing. Run Install_Web_Win11.cmd first.
goto END
:BADCD
echo [ERROR] Cannot access project directory.
:END
echo.
pause
endlocal
