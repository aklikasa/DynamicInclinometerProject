@echo off
setlocal EnableExtensions DisableDelayedExpansion
title WK R7 Web - Optional PLC Dependency
cd /d "%~dp0TiltSensorCalibration"
if not exist ".venv_web\Scripts\python.exe" (
 echo [ERROR] Run Install_Web_Win11.cmd first.
 goto FINISH
)
".venv_web\Scripts\python.exe" -m pip install -r requirements_web_plc.txt
if errorlevel 1 goto FINISH
".venv_web\Scripts\python.exe" -c "from snap7.type import Areas;print('Snap7 old API OK')"
if errorlevel 1 echo [WARN] Snap7 API mismatch. Use the version validated on your original R7 machine.
:FINISH
echo.
pause
endlocal
