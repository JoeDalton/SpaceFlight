@echo off
title SpaceFlight
cd /d %~dp0

if not exist "venv\Scripts\activate.bat" (
    echo No virtual environment found. Please run 2_install_space_flight.bat first.
    pause
    exit /b 1
)

call venv\Scripts\activate.bat
space_flight
pause
