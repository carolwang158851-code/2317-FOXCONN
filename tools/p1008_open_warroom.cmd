@echo off
setlocal EnableExtensions

for %%I in ("%~dp0..") do set "ROOT=%%~fI"
set "PYTHON_EXE=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
set "EXIT_CODE=0"

echo ===================================================
echo   P1008 Launcher app server
echo ===================================================
echo.
echo [ROLE] Open launcher.html for data update, Owner review, and guarded navigation.
echo [RULE] Do not open src files or file:// pages directly.
echo [RULE] Launcher default data update never publishes formal CSV; Owner publish is isolated in Launcher gate.
echo.

if not exist "%PYTHON_EXE%" (
  echo [ERROR] Required bundled Python was not found:
  echo         "%PYTHON_EXE%"
  echo [RULE] System Python fallback is prohibited.
  set "EXIT_CODE=2"
  goto Finish
)

"%PYTHON_EXE%" -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)"
if errorlevel 1 (
  echo [ERROR] Bundled Python must be version 3.12.
  set "EXIT_CODE=4"
  goto Finish
)

"%PYTHON_EXE%" -c "import sys, pydantic; sys.path.insert(0, r'%ROOT%\tools'); import p1008_app_server"
if errorlevel 1 (
  echo [ERROR] Bundled Python launcher dependency preflight failed.
  echo [ERROR] Required imports include pydantic and the P1008 App server entry dependencies.
  set "EXIT_CODE=5"
  goto Finish
)

if not exist "%ROOT%\tools\p1008_open_warroom.py" (
  echo [ERROR] Missing launcher:
  echo         "%ROOT%\tools\p1008_open_warroom.py"
  set "EXIT_CODE=3"
  goto Finish
)

"%PYTHON_EXE%" "%ROOT%\tools\p1008_open_warroom.py" %*
set "EXIT_CODE=%ERRORLEVEL%"

:Finish
echo.
echo [STATUS] Exit code: %EXIT_CODE%
echo.
if /I "%P1008_NO_PAUSE%"=="1" exit /b %EXIT_CODE%
for %%A in (%*) do (
  if /I "%%~A"=="--no-open" exit /b %EXIT_CODE%
)
pause
exit /b %EXIT_CODE%
