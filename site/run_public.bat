@echo off
cd /d "%~dp0"
if not exist releases\app.exe (
  echo Сначала: python ..\build_exe.py
  pause
  exit /b 1
)
start "fucksvinland-site" cmd /c "python server.py"
timeout /t 2 /nobreak >nul
echo.
echo Cloudflare quick tunnel НЕ умеет имя fucksvinland.trycloudflare.com
echo (только случайный *.trycloudflare.com). Имя навсегда:
echo   https://fucksvinland.onrender.com  — Render Blueprint
echo.
echo Сейчас поднимаю туннель без ввода IP...
cloudflared.exe tunnel --url http://127.0.0.1:8080 --protocol http2
pause
