@echo off
setlocal
title CT27 Restore V1.0.2
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Restore_CT27.ps1"
if errorlevel 1 echo RESTORE FAILED.
echo.
echo Press any key to close.
pause >nul
endlocal
