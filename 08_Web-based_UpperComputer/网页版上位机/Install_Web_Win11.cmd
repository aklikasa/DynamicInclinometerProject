@echo off
setlocal EnableExtensions DisableDelayedExpansion
title WK R7 Web - Install Python Dependencies
set "APP_DIR=%~dp0TiltSensorCalibration"
if not exist "%APP_DIR%\native_web\server.py" goto MISSING
cd /d "%APP_DIR%"
if errorlevel 1 goto BADCD
where py >nul 2>nul
if not errorlevel 1 goto LAUNCHER
where python >nul 2>nul
if not errorlevel 1 goto DIRECT
echo [ERROR] Python not found in PATH. Install Python 64-bit.
goto FINISH
:LAUNCHER
py -3 -m venv .venv_web
if errorlevel 1 goto FAILED
goto INSTALL
:DIRECT
python -m venv .venv_web
if errorlevel 1 goto FAILED
:INSTALL
if not exist ".venv_web\Scripts\python.exe" goto FAILED
".venv_web\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements_web.txt
if errorlevel 1 goto FAILED
".venv_web\Scripts\python.exe" -c "import serial,numpy,openpyxl; print('WEB: dependencies OK')"
if errorlevel 1 goto FAILED
echo [SUCCESS] Web dependencies installed into isolated .venv_web.
echo [NEXT] Double-click Start_R7_Web_Win11.cmd.
goto FINISH
:MISSING
echo [ERROR] Not extracted or incomplete ZIP: TiltSensorCalibration\native_web\server.py missing.
goto FINISH
:BADCD
echo [ERROR] Cannot enter project folder. Try D:\WK_R7_WEB.
goto FINISH
:FAILED
echo [ERROR] Dependencies install failed; please copy the full error above.
:FINISH
echo.
pause
endlocal
