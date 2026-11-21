@echo off
cd /d "%~dp0"
python -m unittest tools.test_thermal_adjustable_qa_and_model_catalog tools.test_thermal_model_selection tools.test_thermal_runtime_guard_hotfix tools.test_thermal_run_resume tools.test_thermal_joint_workflow -v
pause
