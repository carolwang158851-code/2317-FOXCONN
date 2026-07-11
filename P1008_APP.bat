@echo off
setlocal EnableExtensions

cd /d "%~dp0"
echo ===================================================
echo   P1008 LAUNCHER WARROOM APP
echo ===================================================
echo.
echo This is the decision-maker entry button.
echo It opens launcher.html for data update, Owner review, and guarded entry to the new UI.
echo.
echo Safety:
echo - Launcher default data update does not publish formal CSV.
echo - Formal CSV append requires the dedicated Owner Formal Publish Gate.
echo - P1008_3_OWNER_PUBLISH_CSV.bat remains a backup path.
echo - News network connectors require APPROVED sources in the manifest.
echo.
call "%~dp0P1008_2_OPEN_WARROOM.bat" %*
exit /b %ERRORLEVEL%
