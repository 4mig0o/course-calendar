@echo off
cd /d "%~dp0"
python --version >nul 2>&1
if errorlevel 1 (
  echo Please install Python 3.11 or newer first.
  pause
  exit /b 1
)
python -m pip install -r requirements.txt
if errorlevel 1 (
  pause
  exit /b 1
)
start "" http://127.0.0.1:8787
python server.py
pause
