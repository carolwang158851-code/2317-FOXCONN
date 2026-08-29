@echo off
setlocal EnableExtensions

for %%I in ("%~dp0..") do set "ROOT=%%~fI"
set "FETCHER=%ROOT%\tools\warroom_data_fetcher_v2.py"
set "PYTHON_EXE=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
set "PYTHON_ARG="
set "EXIT_CODE=0"
set "LOG_DIR=%ROOT%\logs"
set "LOG_FILE=%LOG_DIR%\last_update_data.log"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>nul

echo ===================================================
echo   P1008 staging/runtime data update
echo ===================================================
echo.
echo [ROLE] Fetch latest data and create staging/runtime files.
echo [RULE] Formal CSV files are not modified by this command.
echo [NEXT] Use 3_OWNER... only when Owner wants to publish formal CSV.
echo.

if not exist "%PYTHON_EXE%" (
  echo [ERROR] Approved Bundled Python 3.12 was not found.
  set "EXIT_CODE=2"
  goto Finish
)

"%PYTHON_EXE%" -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Approved runtime must be Python 3.12. System Python fallback is forbidden.
  set "EXIT_CODE=4"
  goto Finish
)

if not exist "%FETCHER%" (
  echo [ERROR] Missing fetcher:
  echo         "%FETCHER%"
  set "EXIT_CODE=3"
  goto Finish
)

echo [INFO] Python : "%PYTHON_EXE%" %PYTHON_ARG%
echo [INFO] Package: "%ROOT%"
echo [INFO] Log    : "%LOG_FILE%"
echo.

"%PYTHON_EXE%" %PYTHON_ARG% "%FETCHER%" --package-root "%ROOT%" %* >"%LOG_FILE%" 2>&1
set "EXIT_CODE=%ERRORLEVEL%"
type "%LOG_FILE%"

:Finish
echo.
echo ===================================================
if "%EXIT_CODE%"=="0" (
  echo [OK] Staging/runtime update completed.
  echo [CHECK] Review staging\YYYY-MM-DD\DRY_RUN.md before Owner publish.
) else (
  echo [ERROR] Update failed. Formal CSV files were unchanged.
)
echo [STATUS] Exit code: %EXIT_CODE%
echo ===================================================
echo.

if /I "%P1008_NO_PAUSE%"=="1" exit /b %EXIT_CODE%
pause
exit /b %EXIT_CODE%
