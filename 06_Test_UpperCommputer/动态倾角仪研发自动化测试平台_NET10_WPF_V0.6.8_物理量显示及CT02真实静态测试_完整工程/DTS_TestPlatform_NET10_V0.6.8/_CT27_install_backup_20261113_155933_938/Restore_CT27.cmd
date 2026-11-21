@echo off
setlocal
title CT-27 Restore
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Restore_CT27.ps1"
if errorlevel 1 echo RESTORE FAILED. Review the message above.
echo.
echo Press any key to close this window.
pause >nul
endlocal
