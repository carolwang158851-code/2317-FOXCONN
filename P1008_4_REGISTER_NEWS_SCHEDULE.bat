@echo off
setlocal EnableExtensions

if /I "%~1"=="--register" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\p1008_register_news_scan_schedule.ps1" -Register
  goto Finish
)

if /I "%~1"=="--remove" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\p1008_register_news_scan_schedule.ps1" -Remove
  goto Finish
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\p1008_register_news_scan_schedule.ps1"

:Finish
if /I "%P1008_NO_PAUSE%"=="1" exit /b %ERRORLEVEL%
pause
exit /b %ERRORLEVEL%
