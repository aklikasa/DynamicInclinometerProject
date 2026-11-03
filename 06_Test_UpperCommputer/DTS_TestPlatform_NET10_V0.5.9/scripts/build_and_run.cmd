@echo off
cd /d "%~dp0.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_windows.ps1" -Run
if errorlevel 1 (
 echo Build or execution failed. See build_logs logs.
 pause
 exit /b 1
)
