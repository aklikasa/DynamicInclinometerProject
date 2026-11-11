@echo off
chcp 65001 > nul
cd /d "%~dp0"
set PYTHONUTF8=1
python -m compileall -q .
if errorlevel 1 goto fail
python tools\test_2fdt_zero_status.py
if errorlevel 1 goto fail
python tools\test_chamber_auto_guard.py
if errorlevel 1 goto fail
python tools\test_plc_auto_page_wiring.py
if errorlevel 1 goto fail
python tools\test_plc_auto_state_machine.py
if errorlevel 1 goto fail
python tools\test_thermal_joint_workflow.py
if errorlevel 1 goto fail
python tools\test_thermal_compensation.py
if errorlevel 1 goto fail
python tools\test_thermal_model_selection.py
if errorlevel 1 goto fail
python tools\test_thermal_workbook.py
if errorlevel 1 goto fail
python tools\test_thermal_page_structure.py
if errorlevel 1 goto fail
python tools\test_thermal_chamber_stability.py
if errorlevel 1 goto fail
python tools\test_thermal_staged_gate_wiring.py
if errorlevel 1 goto fail
python tools\test_thermal_staged_state_machine.py
if errorlevel 1 goto fail
python tools\test_thermal_chip_condition_start.py
if errorlevel 1 goto fail
python tools\test_wk_thermal_stop8_transition.py
if errorlevel 1 goto fail
python tools\test_model_compare.py
if errorlevel 1 goto fail
python tools\test_layout_speed_chamber_fix.py
if errorlevel 1 goto fail
python tools\test_stable_base_regression.py
if errorlevel 1 goto fail
python tools\test_device_uid.py
if errorlevel 1 goto fail
python tools\test_device_sn_autofill.py
if errorlevel 1 goto fail
echo.
echo [PASS] Algorithm, report and static wiring tests passed. This is NOT a real-hardware acceptance test.
pause
exit /b 0
:fail
echo.
echo [FAIL] One or more tests failed. Do NOT run automatic motion until resolved.
pause
exit /b 1
