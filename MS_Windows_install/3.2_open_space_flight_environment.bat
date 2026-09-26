@echo off
title SpaceFlight environment console
cd /d %~dp0

if not exist "venv\Scripts\activate.bat" (
    echo No virtual environment found. Please run 2_install_space_flight.bat first.
    pause
    exit /b 1
)

cmd /k "venv\Scripts\activate.bat & echo SpaceFlight environment loaded & echo Starting interactive mode"
