@echo off
chcp 65001 > nul
cd /d "%~dp0"
python -m unittest tools.test_thermal_continuous_policy_shutdown tools.test_thermal_runtime_guard_hotfix tools.test_thermal_staged_state_machine tools.test_thermal_model_selection tools.test_thermal_workbook -v
pause
