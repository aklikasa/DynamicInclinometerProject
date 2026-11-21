@echo off
chcp 65001 > nul
cd /d "%~dp0"
set PYTHONUTF8=1
python -m compileall -q form\form_thermal_compensation.py thermal_chamber_stability.py thermal_chip_stability.py
if errorlevel 1 goto fail
python tools\test_thermal_chamber_stability.py
if errorlevel 1 goto fail
python tools\test_thermal_staged_state_machine.py
if errorlevel 1 goto fail
python tools\test_thermal_staged_gate_wiring.py
if errorlevel 1 goto fail
python tools\test_wk_thermal_stop8_transition.py
if errorlevel 1 goto fail
python tools\test_wk_thermal_position_dispatch.py
if errorlevel 1 goto fail
python tools\test_thermal_run_resume.py
if errorlevel 1 goto fail
python tools\test_thermal_page_structure.py
if errorlevel 1 goto fail
python tools\test_plc_auto_state_machine.py
if errorlevel 1 goto fail
echo.
echo [PASS] Thermal staged gate, WK position dispatch and stop-transition regression tests passed.
echo This is an offline test only, NOT a real-hardware acceptance test.
pause
exit /b 0
:fail
echo.
echo [FAIL] One or more regression tests failed. Do NOT start automatic motion.
pause
exit /b 1
