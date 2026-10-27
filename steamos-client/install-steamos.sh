#!/bin/bash
# ==============================================================================
# DeckDisplay - Automatic Installation & Setup Script for Steam Deck (SteamOS)
# Prepares environment, installs dependencies, compiles binaries, configures
# systemd service for USB gadget, and creates desktop launcher.
# ==============================================================================
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "===================================================================="
echo "    DeckDisplay - Установка и настройка для Steam Deck (SteamOS)   "
echo "===================================================================="
echo ""

# 1. Проверка прав администратора (sudo)
if [ "$EUID" -ne 0 ]; then
    echo "[DeckDisplay] Требуются привилегии root для установки компонентов."
    echo "[DeckDisplay] Перезапуск скрипта через sudo..."
    exec sudo bash "$0" "$@"
fi

# 2. Проверка и снятие защиты файловой системы SteamOS от записи
if command -v steamos-readonly >/dev/null 2>&1; then
    echo "[DeckDisplay] Отключение защиты файловой системы от записи (steamos-readonly)..."
    steamos-readonly disable || true
fi

# 3. Инициализация ключей и настройка pacman
echo "[DeckDisplay] Настройка pacman и отключение таймаута загрузки..."
if [ -f /etc/pacman.conf ]; then
    sed -i '/^#DisableDownloadTimeout/s/^#//' /etc/pacman.conf 2>/dev/null || true
    if ! grep -q "^DisableDownloadTimeout" /etc/pacman.conf; then
        sed -i '/\[options\]/a DisableDownloadTimeout' /etc/pacman.conf 2>/dev/null || true
    fi
fi

pacman-key --init || true
pacman-key --populate archlinux holo 2>/dev/null || true

# 4. Установка пакетов компиляции и зависимостей с повторными попытками
echo "[DeckDisplay] Установка зависимостей (gcc, make, sdl2, ffmpeg, dnsmasq, pkgconf)..."
SUCCESS=0
for attempt in 1 2 3; do
    echo "[DeckDisplay] Попытка загрузки пакетов ($attempt из 3)..."
    if pacman -Sy --needed --noconfirm gcc make base-devel pkgconf sdl2 ffmpeg dnsmasq linux-api-headers glibc; then
        SUCCESS=1
        break
    fi
    echo "[Предупреждение] Сбой загрузки зеркал, ожидание перед повторной попыткой..."
    sleep 3
done

if [ "$SUCCESS" -ne 1 ]; then
    echo "[Внимание] Не удалось загрузить все пакеты через pacman (проблема со связью к серверам SteamOS)."
    echo "[DeckDisplay] Пробуем установить только gcc и make..."
    pacman -S --needed --noconfirm gcc make || true
fi

# 5. Сборка бинарников
echo "[DeckDisplay] Сборка высокопроизводительных модулей (deckdisplay_touch, deckdisplay_client)..."
cd "$DIR"
if command -v make >/dev/null 2>&1; then
    make clean || true
    make
else
    echo "[DeckDisplay] make не найден, компиляция напрямую через gcc..."
    gcc -O3 -march=znver2 -Wall -Wextra -o deckdisplay_touch deckdisplay_touch.c
    gcc -O3 -march=znver2 -Wall -Wextra -o deckdisplay_client deckdisplay_client.c $(pkg-config --cflags --libs sdl2 libavcodec libavformat libavutil 2>/dev/null || echo "-lSDL2 -lavcodec -lavformat -lavutil")
fi

if [ ! -f "$DIR/deckdisplay_touch" ] || [ ! -f "$DIR/deckdisplay_client" ]; then
    echo "[ОШИБКА] Сборка не удалась. Убедитесь, что установлены gcc и библиотеки."
    exit 1
fi

# 6. Установка прав на исполнение скриптов
chmod +x "$DIR/deckdisplay-gadget.sh"
chmod +x "$DIR/deckdisplay-cleanup.sh"
chmod +x "$DIR/launch_deckdisplay.sh"

# 7. Настройка udev-правила для доступа к /dev/hidg* пользователю deck
echo "[DeckDisplay] Установка udev-правила для /dev/hidg*..."
cat << 'EOF' > /etc/udev/rules.d/99-deckdisplay-hid.rules
KERNEL=="hidg*", MODE="0666"
EOF
udevadm control --reload-rules 2>/dev/null || true
udevadm trigger 2>/dev/null || true

# 8. Установка и активация системного сервиса
echo "[DeckDisplay] Установка системного сервиса deckdisplay-gadget.service..."
SERVICE_FILE="/etc/systemd/system/deckdisplay-gadget.service"
cat << EOF > "$SERVICE_FILE"
[Unit]
Description=DeckDisplay Composite USB Gadget (CDC-NCM + HID Touchscreen)
After=network.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=$DIR/deckdisplay-gadget.sh
ExecStop=$DIR/deckdisplay-cleanup.sh

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable deckdisplay-gadget.service
systemctl restart deckdisplay-gadget.service || true

# 9. Создание ярлыка на Рабочем столе
DESKTOP_DIR="/home/deck/Desktop"
if [ -d "$DESKTOP_DIR" ]; then
    echo "[DeckDisplay] Создание ярлыка запуска на Рабочем столе..."
    cat << EOF > "$DESKTOP_DIR/DeckDisplay.desktop"
[Desktop Entry]
Name=DeckDisplay Monitor
Comment=Использовать Steam Deck как второй монитор по USB Type-C
Exec=$DIR/launch_deckdisplay.sh
Icon=video-display
Terminal=false
Type=Application
Categories=Game;Utility;
EOF
    chmod +x "$DESKTOP_DIR/DeckDisplay.desktop"
    chown deck:deck "$DESKTOP_DIR/DeckDisplay.desktop" 2>/dev/null || true
fi

echo ""
echo "===================================================================="
echo "                   УСТАНОВКА УСПЕШНО ЗАВЕРШЕНА!                    "
echo "===================================================================="
echo ""
echo "Следующие шаги:"
echo "1. Проверьте BIOS Steam Deck (USB Dual Role Device -> DRD):"
echo "   Выключите Deck -> зажмите 'Volume +' и нажмите 'Power' ->"
echo "   Setup Utility -> Advanced -> USB Configuration -> 'DRD'."
echo ""
echo "2. Добавьте ярлык в Steam для запуска из Gaming Mode:"
echo "   Откройте клиент Steam на Deck -> Игры -> Добавить стороннюю игру ->"
echo "   выберите '$DIR/launch_deckdisplay.sh'."
echo ""
echo "3. Подключите кабель USB Type-C к ПК и запустите DeckDisplay!"
echo "===================================================================="
