@echo off
title Updating SpaceFlight
cd /d %~dp0

if not exist "venv\Scripts\activate.bat" (
    echo No virtual environment found. Please run 2_install_space_flight.bat first.
    pause
    exit /b 1
)

echo Make sure you have pulled the latest source code ^(git pull^) before running this.
echo.

call venv\Scripts\activate.bat
set POETRY_DYNAMIC_VERSIONING_BYPASS=0.0.0
pip install -e .. --upgrade
if errorlevel 1 (
    echo.
    echo Update failed. Please check the errors above.
    pause
    exit /b 1
)

echo.
echo Finished updating SpaceFlight.
pause
