@echo off
setlocal
cd /d %~dp0

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -m codex_stats %*
  if errorlevel 1 (
    echo.
    echo Failed to start. Check the messages above.
    pause
  )
  exit /b
)

where python >nul 2>nul
if %errorlevel%==0 (
  python -m codex_stats %*
  if errorlevel 1 (
    echo.
    echo Failed to start. Install real Python 3.9+ if needed.
    pause
  )
  exit /b
)

echo Python 3.9+ not found. Install Python and enable "Add python.exe to PATH".
pause
exit /b 1
