@echo off
setlocal EnableExtensions

for %%I in ("%~dp0..") do set "ROOT=%%~fI"
set "UPDATER=%ROOT%\tools\warroom_market_activity_updater.py"
set "PYTHON_EXE=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
set "LOG_DIR=%ROOT%\logs"
set "LOG_FILE=%LOG_DIR%\last_market_activity_update.log"
set "EXIT_CODE=0"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>nul

echo ===================================================
echo   P1008 TWSE market activity incremental update
echo ===================================================
echo [RULE] Bundled Python 3.12 only; no System Python fallback.
echo [RULE] TWSE TLS verification stays enabled; max three monthly files.
echo [RULE] Candidate-only: this command never modifies formal CSV or manifest.
echo [RULE] Formal publish requires a separate Owner-gated owner_publish_csv_v2 action.

if not exist "%PYTHON_EXE%" (
  echo [ERROR] Approved Bundled Python is missing: "%PYTHON_EXE%"
  set "EXIT_CODE=21"
  goto Finish
)

"%PYTHON_EXE%" -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Approved runtime must be Python 3.12. System Python fallback is forbidden.
  set "EXIT_CODE=22"
  goto Finish
)

if not exist "%UPDATER%" (
  echo [ERROR] Missing market activity updater: "%UPDATER%"
  set "EXIT_CODE=23"
  goto Finish
)

echo [INFO] Python : "%PYTHON_EXE%"
echo [INFO] Package: "%ROOT%"
echo [INFO] Log    : "%LOG_FILE%"

"%PYTHON_EXE%" "%UPDATER%" --package-root "%ROOT%" %* >"%LOG_FILE%" 2>&1
set "EXIT_CODE=%ERRORLEVEL%"
type "%LOG_FILE%"

:Finish
echo [STATUS] Exit code: %EXIT_CODE%
echo ===================================================

if /I "%P1008_NO_PAUSE%"=="1" exit /b %EXIT_CODE%
pause
exit /b %EXIT_CODE%
