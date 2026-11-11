@echo off
setlocal EnableExtensions DisableDelayedExpansion
title WK IMU R7 - Environment Diagnostic
cd /d "%~dp0TiltSensorCalibration"
if not exist ".venv_web\Scripts\python.exe" (
 echo [ERROR] Install first: Install_Web_Win11.cmd
 goto FINISH
)
".venv_web\Scripts\python.exe" -m native_web.check_environment
".venv_web\Scripts\python.exe" -m unittest discover -s native_web/tests -v
:FINISH
echo.
pause
endlocal
