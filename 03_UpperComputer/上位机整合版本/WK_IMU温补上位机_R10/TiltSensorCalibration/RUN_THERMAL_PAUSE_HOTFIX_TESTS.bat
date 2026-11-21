@echo off
chcp 65001 > nul
cd /d "%~dp0"
set PYTHONUTF8=1
python -m compileall -q .
if errorlevel 1 goto fail
python tools\test_thermal_runtime_guard_hotfix.py
if errorlevel 1 goto fail
python tools\test_thermal_joint_workflow.py
if errorlevel 1 goto fail
echo.
echo [PASS] Temperature runtime-guard offline tests passed. Real-device acceptance STILL required.
pause
exit /b 0
:fail
echo.
echo [FAIL] Temperature runtime-guard offline tests FAILED. Do not run automated motion.
pause
exit /b 1
