@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
set "PY=C:\Users\Administrator\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" dingding_win.py --test
