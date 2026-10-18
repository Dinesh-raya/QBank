@echo off
:: QBank Web App Local Preview Server
:: Double-click this file to launch QBank in your browser

echo Starting QBank Web App...
echo Password: pass123
echo.
echo Opening http://localhost:8080 in your browser...
start "" http://localhost:8080
python -m http.server 8080 -d "%~dp0"
pause
