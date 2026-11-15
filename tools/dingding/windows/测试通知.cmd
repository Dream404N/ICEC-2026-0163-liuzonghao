@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
set "EXE="
for %%F in ("%~dp0..\dist\*.exe") do set "EXE=%%~fF"
if not defined EXE (
  echo ERROR: dist\*.exe not found.
  pause >nul
  exit /b 1
)
"%EXE%" --test
