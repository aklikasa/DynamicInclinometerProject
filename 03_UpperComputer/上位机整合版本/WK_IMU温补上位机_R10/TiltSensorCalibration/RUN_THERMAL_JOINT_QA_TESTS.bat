@echo off
chcp 65001 > nul
cd /d "%~dp0"
set PYTHONUTF8=1
python -m compileall -q thermal_reference_diagnostics.py thermal_runtime_guard.py thermal_incomplete_report.py thermal_run_resume.py form\form_thermal_compensation.py
if errorlevel 1 goto fail
python -m unittest discover -s tools -p "test_thermal_joint_workflow.py" -v
if errorlevel 1 goto fail
echo [PASS] 离线测速/温漂/待补测/恢复/报告测试通过。必须再进行Windows实机和急停验收。
pause
exit /b 0
:fail
echo [FAIL] 测试失败，禁止执行实际转台自动运动。
pause
exit /b 1
