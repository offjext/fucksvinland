@echo off
cd /d "%~dp0"
if not exist releases\app.exe (
  echo Сначала: python ..\build_exe.py
  pause
  exit /b 1
)
start "fucksvinland-site" cmd /c "python server.py"
timeout /t 2 /nobreak >nul
echo Сайт: https://fucksvinland.loca.lt
npx --yes localtunnel --port 8080 --subdomain fucksvinland
pause
