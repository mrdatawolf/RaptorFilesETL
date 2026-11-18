@echo off
cd /d "%~dp0" || exit /b 2
.venv\Scripts\raptor-etl.exe run %*
exit /b %errorlevel%
