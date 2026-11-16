@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 请输入包含同一批次升温和降温THERM_实验记录的父目录:
set /p "R4_PARENT=> "
if "%R4_PARENT%"=="" (
 echo 未输入文件夹，退出。
 pause
 exit /b 2
)
py -3 production_cycle_analysis.py "%R4_PARENT%"
pause
