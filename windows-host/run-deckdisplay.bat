@echo off
title DeckDisplay Host
cd /d "%~dp0"

if exist "DeckDisplay.exe" (
    echo Starting DeckDisplay GUI...
    start "" "DeckDisplay.exe"
    exit /b 0
)

if exist "dist\DeckDisplay.exe" (
    echo Starting DeckDisplay GUI from dist...
    start "" "dist\DeckDisplay.exe"
    exit /b 0
)

where python >nul 2>nul
if %errorlevel% equ 0 (
    echo Starting DeckDisplay via Python...
    start "" pythonw deckdisplay_app.py
    exit /b 0
)

echo Starting DeckDisplay via PowerShell CLI Watchdog...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-DeckDisplay.ps1"
pause
