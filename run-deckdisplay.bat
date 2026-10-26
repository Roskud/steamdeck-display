@echo off
title DeckDisplay Host
cd /d "%~dp0"

if exist "DeckDisplay.exe" (
    echo Starting DeckDisplay GUI...
    start "" "DeckDisplay.exe"
    exit /b 0
)

if exist "windows-host\DeckDisplay.exe" (
    echo Starting DeckDisplay GUI from windows-host...
    start "" "windows-host\DeckDisplay.exe"
    exit /b 0
)

if exist "windows-host\run-deckdisplay.bat" (
    call "windows-host\run-deckdisplay.bat"
    exit /b 0
)

pause
