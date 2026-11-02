@echo off
setlocal
cd /d "%~dp0"
where xelatex >nul 2>nul || (echo XeLaTeX not found. Install MiKTeX or TeX Live. & exit /b 1)
xelatex -interaction=nonstopmode -halt-on-error -file-line-error main.tex > build_pass1.log 2>&1
if errorlevel 1 (echo FIRST PASS FAILED: check build_pass1.log & exit /b 1)
xelatex -interaction=nonstopmode -halt-on-error -file-line-error main.tex > build_pass2.log 2>&1
if errorlevel 1 (echo SECOND PASS FAILED: check build_pass2.log & exit /b 1)
echo Build passed: main.pdf
exit /b 0
