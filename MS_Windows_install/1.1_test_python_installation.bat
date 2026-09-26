@echo off
setlocal
cd /d %~dp0

where python >nul 2>&1
if errorlevel 1 (
    echo Python was not found in your PATH.
    echo Please install Python 3.12, 3.13, or 3.14 from python.org and make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

for /f "delims=" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i
echo Detected: %PYTHON_VERSION%

python -c "import sys; sys.exit(0 if (3,12) <= sys.version_info < (3,15) else 1)"
if errorlevel 1 (
    echo.
    echo This Python version is NOT compatible with SpaceFlight ^(requires 3.12.x, 3.13.x or 3.14.x^).
    echo Please install a compatible version from python.org.
) else (
    echo.
    echo This Python version is compatible. You can proceed to run 2_install_space_flight.bat
)

pause
