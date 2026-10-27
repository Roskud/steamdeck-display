#!/bin/bash
# ==============================================================================
# DeckDisplay - Launcher Script for SteamOS Gaming Mode / Desktop
# Starts the background touch daemon, launches the hardware video client,
# and performs clean termination upon exiting.
# ==============================================================================

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Проверка наличия скомпилированных бинарников
if [ ! -f "$DIR/deckdisplay_client" ] || [ ! -f "$DIR/deckdisplay_touch" ]; then
    echo "[DeckDisplay Launcher] Бинарные файлы не найдены! Выполняем автоматическую сборку (make)..."
    make -C "$DIR" || {
        echo "[ОШИБКА] Не удалось собрать бинарники. Запустите 'make' вручную."
        exit 1
    }
fi

# Остановка старых процессов, если они остались активными
pkill -f "$DIR/deckdisplay_touch" 2>/dev/null || true
pkill -f "$DIR/deckdisplay_client" 2>/dev/null || true

# Проверка готовности HID-устройства тачскрина
TOUCH_PID=""
if [ -e /dev/hidg0 ]; then
    echo "[DeckDisplay Launcher] Запуск демона сенсорного ввода..."
    "$DIR/deckdisplay_touch" /dev/hidg0 &
    TOUCH_PID=$!
else
    echo "[DeckDisplay Launcher] Внимание: /dev/hidg0 не найден. Проверьте статус deckdisplay-gadget.service."
fi

# Функция перехвата сигналов для корректной остановки
cleanup() {
    echo "[DeckDisplay Launcher] Остановка фоновых процессов..."
    if [ -n "$TOUCH_PID" ]; then
        kill "$TOUCH_PID" 2>/dev/null || true
    fi
    pkill -f "$DIR/deckdisplay_touch" 2>/dev/null || true
    exit 0
}
trap cleanup SIGINT SIGTERM EXIT

# Запуск аппаратного видеоклиента
PORT="${1:-5000}"
URL="udp://0.0.0.0:${PORT}?fifo_size=65536&overrun_nonfatal=1&timeout=200000"

echo "[DeckDisplay Launcher] Запуск видеоклиента на порту $PORT..."
"$DIR/deckdisplay_client" "$URL"
