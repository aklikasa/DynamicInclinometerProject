@echo off
chcp 65001 >nul
cd /d "%~dp0.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_windows.ps1" %*
if errorlevel 1 (
 echo.
 echo Build failed. See build_logs\last_build_debug.log for the FIRST actual error.
 pause
 exit /b 1
)
echo Build verified.
pause
