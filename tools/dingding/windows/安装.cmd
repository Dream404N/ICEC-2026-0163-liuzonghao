@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
rem 用通配符定位 EXE，避免 cmd 代码页把中文文件名读乱
set "EXE="
for %%F in ("%~dp0..\dist\*.exe") do set "EXE=%%~fF"
if not defined EXE (
  echo ERROR: dist\*.exe not found. Run: python tools\dingding\build_exe.py
  pause >nul
  exit /b 1
)
set "REPO=%~dp0..\..\.."
set "WS=%~dp0..\..\..\.."
set "PY=C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe"
if not exist "%PY%" set "PY=python"
"%EXE%" --install --repo-root "%REPO%" --workspace "%WS%" --python "%PY%"
echo.
echo Installed. A test notification just popped up (auto-closes in 5 seconds).
echo The settings window opens too. Desktop shortcuts: settings / test notification.
echo First cold start of a single-file EXE takes about 5-7 seconds to unpack.
pause >nul
