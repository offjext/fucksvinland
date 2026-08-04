@echo off

cd /d "%~dp0"

python build_exe.py

if errorlevel 1 (

  echo BUILD FAILED

  pause

  exit /b 1

)

echo.

echo Done: dist\ddjj.exe

pause


