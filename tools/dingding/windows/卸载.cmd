@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
set "EXE="
for %%F in ("%LOCALAPPDATA%\DingDingTimetable\*.exe") do set "EXE=%%~fF"
if not defined EXE for %%F in ("%~dp0..\dist\*.exe") do set "EXE=%%~fF"
if not defined EXE (
  echo ERROR: EXE not found.
  pause >nul
  exit /b 1
)
"%EXE%" --uninstall
echo.
echo Startup entry removed. Click "Exit" in the settings window, or reboot, to stop it.
pause >nul
