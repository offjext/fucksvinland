@echo off
cd /d "%~dp0"
if not exist releases\app.exe (
  echo Copy dist\ddjj.exe to site\releases\app.exe first
  pause
  exit /b 1
)
pip install -r requirements.txt -q
python server.py
pause
