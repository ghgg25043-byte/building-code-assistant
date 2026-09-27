@echo off
setlocal
cd /d "%~dp0"
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "BCA_PYTHON=python"
    goto ready
)
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "BCA_PYTHON=py -3"
    goto ready
)
echo Python 3.10 or newer was not found.
echo Install Python, enable PATH or the py launcher, then run this file again.
echo See README.md for setup instructions.
pause
exit /b 1

:ready
echo Starting Building Code Assistant. The terminal will show the local URL.
echo Default port: 8765. A pre-set PORT environment variable overrides it.
echo If the port is in use, run in PowerShell: $env:PORT='8766'; .\start.bat
echo Press Ctrl+C to stop the server. Keep this window open while using the app.
set "PYTHONUTF8=1"
%BCA_PYTHON% -u app.py
set "BCA_EXIT_CODE=%ERRORLEVEL%"
pause
exit /b %BCA_EXIT_CODE%
