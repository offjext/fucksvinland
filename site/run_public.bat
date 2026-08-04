@echo off
cd /d "%~dp0"
if not exist releases\app.exe (
  echo Сначала: python ..\build_exe.py
  pause
  exit /b 1
)
start "fucksvinland-site" cmd /c "python server.py"
timeout /t 2 /nobreak >nul
echo Запуск Cloudflare tunnel (без ввода IP)...
cloudflared.exe tunnel --url http://127.0.0.1:8080
pause
