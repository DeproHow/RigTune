@echo off
title RigTune
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python is not installed. Get it from https://www.python.org/downloads/
  echo IMPORTANT: tick "Add python.exe to PATH" in the installer.
  pause
  exit /b
)
echo Installing / checking requirements...
python -m pip install -q -r requirements.txt
python main.py
if errorlevel 1 pause
