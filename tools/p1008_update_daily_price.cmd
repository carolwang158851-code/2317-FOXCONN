@echo off
setlocal EnableExtensions
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
set "PYTHON_EXE=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
set "UPDATER=%ROOT%\tools\warroom_daily_price_updater.py"
set "LOG_DIR=%ROOT%\logs"
set "LOG_FILE=%ROOT%\logs\last_daily_price_update.log"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>nul
if not exist "%PYTHON_EXE%" echo [ERROR] Approved Bundled Python is missing: "%PYTHON_EXE%" & exit /b 21
"%PYTHON_EXE%" -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>nul
if errorlevel 1 echo [ERROR] Approved runtime must be Python 3.12. & exit /b 22
echo [INFO] Python executable: "%PYTHON_EXE%"
"%PYTHON_EXE%" "%UPDATER%" --package-root "%ROOT%" %* >"%LOG_FILE%" 2>&1
set "EXIT_CODE=%ERRORLEVEL%"
type "%LOG_FILE%"
exit /b %EXIT_CODE%
