@echo off
title DeckDisplay Windows Host Watchdog
echo Запуск DeckDisplay Watchdog...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-DeckDisplay.ps1"
pause
