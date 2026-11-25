@echo off
title Build RigTune.exe
cd /d "%~dp0"
python -m pip install -q -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --onefile --windowed --uac-admin --name RigTune --collect-all customtkinter main.py
echo.
echo Done! Your app is in the "dist" folder: dist\RigTune.exe
pause
