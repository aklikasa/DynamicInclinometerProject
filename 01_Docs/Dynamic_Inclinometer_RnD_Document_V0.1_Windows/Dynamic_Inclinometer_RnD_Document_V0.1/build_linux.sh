#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
xelatex -interaction=nonstopmode -halt-on-error -file-line-error main.tex > build_pass1.log 2>&1
xelatex -interaction=nonstopmode -halt-on-error -file-line-error main.tex > build_pass2.log 2>&1
echo "Build passed: main.pdf"
