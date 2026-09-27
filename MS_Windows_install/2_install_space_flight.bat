@echo off
setlocal
title Installing SpaceFlight
cd /d %~dp0

echo Checking for Python...
where python >nul 2>&1
if errorlevel 1 (
    echo Python was not found. Please run 1.1_test_python_installation.bat first.
    pause
    exit /b 1
)

echo Creating virtual environment...
python -m venv venv
if errorlevel 1 (
    echo Failed to create the virtual environment.
    pause
    exit /b 1
)

call venv\Scripts\activate.bat
if errorlevel 1 (
    echo Failed to activate the virtual environment.
    pause
    exit /b 1
)

echo Installing SpaceFlight and its dependencies ^(this will take a few minutes^)...
set POETRY_DYNAMIC_VERSIONING_BYPASS=0.0.0
pip install -e ..
if errorlevel 1 (
    echo.
    echo Installation failed. Please check the errors above.
    pause
    exit /b 1
)

echo.
echo Finished installing SpaceFlight.
pause
