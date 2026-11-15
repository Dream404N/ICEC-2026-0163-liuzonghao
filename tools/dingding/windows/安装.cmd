@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
set "PY=C:\Users\Administrator\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not exist "%PY%" set "PY=python"
echo Installing DingDing Timetable ...
"%PY%" dingding_win.py --install
echo.
echo Done. A test notification should have appeared (auto-closes in 5s).
echo The desktop shortcut "DingDing - Test Notification" can test it any time.
pause >nul
