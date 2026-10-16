@echo off
setlocal
title Strata HUD
cd /d "%~dp0"
if not exist "%~dp0strata-chat-hud.html" (
  echo strata-chat-hud.html is missing next to this file.
  pause
  exit /b 1
)
copy /Y "%~dp0strata-chat-hud.html" "%~dp0serve\web\index.html" >nul
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo The Python environment is missing. Run START-HERE.bat once, then this again.
  pause
  exit /b 1
)
netstat -ano | findstr /C:":15091 " | findstr "LISTENING" >nul
if errorlevel 1 start "Strata catalog" /MIN "%PY%" "%~dp0serve\hud_catalog.py"
netstat -ano | findstr /C:":15080 " | findstr "LISTENING" >nul
if errorlevel 1 (
  start "Strata HUD" "%PY%" "%~dp0serve\server.py" --engine strata --config "%~dp0strata-hud-launch.json" --port 15080 --open
) else (
  start "" "http://127.0.0.1:15080/"
)
