@echo off
chcp 65001 > nul
cd /d "%~dp0"
where xelatex >nul 2>&1
if errorlevel 1 (
  echo [ERROR] No XeLaTeX detected. Install TeX Live or MiKTeX and check PATH.
  pause
  exit /b 1
)
xelatex -interaction=nonstopmode -halt-on-error main.tex
if errorlevel 1 (echo First build FAILED. & pause & exit /b 1)
xelatex -interaction=nonstopmode -halt-on-error main.tex
if errorlevel 1 (echo Second build FAILED. & pause & exit /b 1)
echo Build OK: main.pdf
pause
