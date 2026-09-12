@echo off
cd /d "%~dp0"
"%~dp0.venv\Scripts\python.exe" -m pip install -r requirements.txt
"%~dp0.venv\Scripts\python.exe" app.py