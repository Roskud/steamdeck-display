#!/bin/bash
# portable_run.sh
# Запуск клиента напрямую из папки
cd "$(dirname "$0")"
./deckdisplay_client udp://0.0.0.0:5000
