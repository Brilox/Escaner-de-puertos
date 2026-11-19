@echo off
cd /d "%~dp0"
python panel_admin.py
if errorlevel 1 pause
