@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
python -m compileall -q thermal_compensation.py thermal_variable_temperature.py thermal_model_selection.py thermal_temperature_inputs.py thermal_excel_report.py thermal_gyro_multirate.py thermal_reference_diagnostics.py thermal_runtime_guard.py form\form_thermal_compensation.py
if errorlevel 1 goto fail
python tools\test_thermal_split_temperature_plan.py
if errorlevel 1 goto fail
python tools\test_thermal_user_rates.py
if errorlevel 1 goto fail
python tools\test_thermal_joint_workflow.py
if errorlevel 1 goto fail
python tools\test_thermal_model_selection.py
if errorlevel 1 goto fail
python tools\test_thermal_cubic_temperature.py
if errorlevel 1 goto fail
python tools\test_thermal_compensation.py
if errorlevel 1 goto fail
python tools\test_thermal_retry_alignment.py
if errorlevel 1 goto fail
python tools\test_thermal_workbook.py
if errorlevel 1 goto fail
python tools\test_thermal_page_structure.py
if errorlevel 1 goto fail
echo [PASS] 28套温补模型、自定义拟合与验证速率、温漂/安全停车、待补测续做、Excel与温补离线回归通过（仅离线，非实机验收）
pause
exit /b 0
:fail
echo [FAIL] 温补离线回归失败，禁止作为已验收版本使用
pause
exit /b 1
