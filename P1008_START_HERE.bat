@echo off
setlocal EnableExtensions

cd /d "%~dp0"

:Menu
cls
echo ===================================================
echo   P1008 WARROOM START HERE
echo ===================================================
echo.
echo [1] Open P1008 Launcher
echo [2] Update data staging/runtime
echo [3] Run observation-only news scan
echo [4] Generate daily report
echo [5] Preview/register news schedule tool
echo [6] Open docs operator guide
echo [Q] Quit
echo.
echo Rules:
echo - News scan v1 is dry-run/no-network unless separately approved.
echo - Generated reports do not modify formal CSV.
echo - Formal CSV append requires Launcher Owner Gate or backup publish BAT.
echo.
choice /C 123456Q /N /M "Select: "
set "MENU_CHOICE=%ERRORLEVEL%"

if "%MENU_CHOICE%"=="7" goto End
if "%MENU_CHOICE%"=="6" goto Readme
if "%MENU_CHOICE%"=="5" goto Schedule
if "%MENU_CHOICE%"=="4" goto Report
if "%MENU_CHOICE%"=="3" goto News
if "%MENU_CHOICE%"=="2" goto Update
if "%MENU_CHOICE%"=="1" goto Open
goto Menu

:Open
call "%~dp0P1008_APP.bat"
goto Again

:Update
call "%~dp0P1008_1_UPDATE_DATA.bat"
goto Again

:News
call "%~dp0P1008_4_NEWS_SCAN.bat" --dry-run --no-network
goto Again

:Report
call "%~dp0P1008_5_GENERATE_REPORTS.bat" --period daily
goto Again

:Schedule
call "%~dp0P1008_4_REGISTER_NEWS_SCHEDULE.bat"
goto Again

:Readme
start "" "%~dp0docs\README_START_HERE.md"
goto Again

:Again
echo.
choice /C YN /N /M "Return to menu? [Y/N] "
if errorlevel 2 goto End
goto Menu

:End
exit /b 0
