@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PYTHON_EXE=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%PYTHON_EXE%" (
  echo [FAIL_CLOSED] Approved Bundled Python is missing.
  exit /b 21
)
"%PYTHON_EXE%" -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>nul
if errorlevel 1 (
  echo [FAIL_CLOSED] Approved runtime must be Python 3.12; fallback is forbidden.
  exit /b 22
)
set "PYTHONPATH=%~dp0modules\p1008_research_plugin\src"
"%PYTHON_EXE%" "%~dp0tools\p1008_build_report.py" --package-root "%~dp0." %*
exit /b %ERRORLEVEL%
