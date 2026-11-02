@echo off
cd /d "%~dp0.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_windows.ps1"
if errorlevel 1 (
  echo BUILD FAILED; inspect the first error above.
  exit /b 1
)
echo BUILD AND C# MODULE SELF-TEST FINISHED.
