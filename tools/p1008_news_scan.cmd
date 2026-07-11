@echo off
setlocal EnableExtensions

for %%I in ("%~dp0..") do set "ROOT=%%~fI"
set "SCANNER=%ROOT%\tools\warroom_news_scanner_v2.py"
set "PYTHON_EXE="
set "PYTHON_ARG="
set "EXIT_CODE=0"
set "LOG_DIR=%ROOT%\logs"
set "LOG_FILE=%LOG_DIR%\last_news_scan.log"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>nul

echo ===================================================
echo   P1008 scheduled news scan
echo ===================================================
echo.
echo [ROLE] Create observation-only news/event staging and runtime snapshot.
echo [RULE] Formal CSV files are not modified by this command.
echo [RULE] HOLD is not changed; REVIEW_REQUIRED only shows HOLD_UNDER_REVIEW in UI.
echo [RULE] Enabled APPROVED public connectors may be fetched, but all outputs remain observation-only.
echo.

for /f "delims=" %%P in ('%SystemRoot%\System32\where.exe py 2^>nul') do (
  if not defined PYTHON_EXE (
    set "PYTHON_EXE=%%P"
    set "PYTHON_ARG=-3"
  )
)
if not defined PYTHON_EXE (
  for /f "delims=" %%P in ('%SystemRoot%\System32\where.exe python 2^>nul') do (
    if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
  )
)
if not defined PYTHON_EXE if exist "%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe" set "PYTHON_EXE=%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe"
if not defined PYTHON_EXE if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" set "PYTHON_EXE=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if not defined PYTHON_EXE (
  echo [ERROR] Python 3 was not found. Install Python or add py/python to PATH.
  set "EXIT_CODE=2"
  goto Finish
)

if not exist "%SCANNER%" (
  echo [ERROR] Missing scanner:
  echo         "%SCANNER%"
  set "EXIT_CODE=3"
  goto Finish
)

echo [INFO] Python : "%PYTHON_EXE%" %PYTHON_ARG%
echo [INFO] Package: "%ROOT%"
echo [INFO] Log    : "%LOG_FILE%"
echo.

"%PYTHON_EXE%" %PYTHON_ARG% "%SCANNER%" --package-root "%ROOT%" %* >"%LOG_FILE%" 2>&1
set "EXIT_CODE=%ERRORLEVEL%"
type "%LOG_FILE%"

:Finish
echo.
echo ===================================================
if "%EXIT_CODE%"=="0" (
  echo [OK] News scan completed.
  echo [CHECK] Review runtime\warroom_news_scan_snapshot.json and staging\YYYY-MM-DD\NEWS_SCAN.md.
) else (
  echo [ERROR] News scan failed. Formal CSV files were unchanged.
)
echo [STATUS] Exit code: %EXIT_CODE%
echo ===================================================
echo.

if /I "%P1008_NO_PAUSE%"=="1" exit /b %EXIT_CODE%
pause
exit /b %EXIT_CODE%
