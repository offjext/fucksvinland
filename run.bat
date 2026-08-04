@echo off
cd /d "%~dp0"
start "" pythonw "%~dp0ddjj.py"
if errorlevel 1 python "%~dp0ddjj.py"
