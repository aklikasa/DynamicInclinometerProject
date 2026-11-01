@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
where py >nul 2>nul
if %errorlevel%==0 (
  set "PYCMD=py -3"
) else (
  set "PYCMD=python"
)
if not exist ".venv\Scripts\python.exe" (
  echo [1/3] 创建 Python 虚拟环境...
  %PYCMD% -m venv ".venv" || goto :failed
)
echo [2/3] 安装/检查依赖...
".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :failed
echo [3/3] 启动静态角度检测工作台...
".venv\Scripts\python.exe" main.py
if errorlevel 1 goto :failed
exit /b 0
:failed
echo.
echo 工作台出现错误。请将以下日志发给开发人员：
echo %%LOCALAPPDATA%%\StaticAngleLab\logs\workbench_errors.log
echo DLL通信异常请先核实实体急停状态。
pause
exit /b 1
