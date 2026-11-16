@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3 -m unittest tools.test_r5_production tools.test_r4_production -v
if errorlevel 1 pause
