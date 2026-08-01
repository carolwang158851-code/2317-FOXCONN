@echo off
setlocal EnableExtensions

for %%I in ("%~dp0..") do set "ROOT=%%~fI"
set "PUBLISHER=%ROOT%\tools\owner_publish_csv_v2.py"
set "PYTHON_EXE="
set "PYTHON_ARG="
set "DATE_ARG=%~1"
set "FORWARD_ARGS=%*"
set "EXIT_CODE=0"
set "LOG_DIR=%ROOT%\logs"
set "LOG_FILE=%LOG_DIR%\last_owner_publish_review.log"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>nul

echo ===================================================
echo   P1008 Owner formal CSV publish checkpoint
echo ===================================================
echo.
echo [ROLE] Review staging candidates and publish formal CSV only after Owner approval.
echo [RULE] This command does not fetch new data.
echo [RULE] Review mode does not modify formal CSV.
echo [RULE] Publish mode appends only after exact approval phrase.
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

if not exist "%PUBLISHER%" (
  echo [ERROR] Missing publisher:
  echo         "%PUBLISHER%"
  set "EXIT_CODE=3"
  goto Finish
)

if defined DATE_ARG (
  if /I not "%~1"=="--date" (
    if not "%DATE_ARG:~0,2%"=="--" set "FORWARD_ARGS=--date %DATE_ARG%"
  )
)

echo [STEP] Review latest staging candidate.
"%PYTHON_EXE%" %PYTHON_ARG% "%PUBLISHER%" --package-root "%ROOT%" %FORWARD_ARGS% >"%LOG_FILE%" 2>&1
set "EXIT_CODE=%ERRORLEVEL%"
type "%LOG_FILE%"
echo.

if not "%EXIT_CODE%"=="0" (
  echo [STOP] Review reported a blocking issue. Formal CSV was not changed.
  goto Finish
)

findstr /C:"NO_ACTION_REQUIRED: YES" "%LOG_FILE%" >nul 2>nul
if "%ERRORLEVEL%"=="0" (
  set "EXIT_CODE=0"
  echo [OK] Formal CSV already contains this candidate date. No publish prompt is needed.
  goto Finish
)

if /I "%P1008_NO_PROMPT%"=="1" goto Finish

set /p "OWNER_MODE=Type PUBLISH to enter formal publish mode, or press Enter to exit review-only: "
if /I not "%OWNER_MODE%"=="PUBLISH" (
  echo [OK] Review-only completed. Formal CSV was not changed.
  goto Finish
)

echo.
echo [PUBLISH] Type the exact approval phrase shown by the tool.
"%PYTHON_EXE%" %PYTHON_ARG% "%PUBLISHER%" --package-root "%ROOT%" %FORWARD_ARGS% --publish
set "EXIT_CODE=%ERRORLEVEL%"

:Finish
echo.
echo [STATUS] Exit code: %EXIT_CODE%
echo.
if /I "%P1008_NO_PAUSE%"=="1" exit /b %EXIT_CODE%
pause
exit /b %EXIT_CODE%
