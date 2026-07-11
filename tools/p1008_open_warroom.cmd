@echo off
setlocal EnableExtensions

for %%I in ("%~dp0..") do set "ROOT=%%~fI"
set "PYTHON_EXE="
set "PYTHON_ARG="
set "EXIT_CODE=0"

echo ===================================================
echo   P1008 Launcher app server
echo ===================================================
echo.
echo [ROLE] Open launcher.html for data update, Owner review, and guarded navigation.
echo [RULE] Do not open src files or file:// pages directly.
echo [RULE] Launcher default data update never publishes formal CSV; Owner publish is isolated in Launcher gate.
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

if not exist "%ROOT%\tools\p1008_open_warroom.py" (
  echo [ERROR] Missing launcher:
  echo         "%ROOT%\tools\p1008_open_warroom.py"
  set "EXIT_CODE=3"
  goto Finish
)

"%PYTHON_EXE%" %PYTHON_ARG% "%ROOT%\tools\p1008_open_warroom.py" --package-root "%ROOT%" %*
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
