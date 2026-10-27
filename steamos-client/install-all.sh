#!/bin/bash
set -e
echo "--- DeckDisplay: Универсальная установка ---"

# 1. Проверка компиляторов
if ! command -v gcc &> /dev/null || ! command -v make &> /dev/null; then
    echo "[!] Компилятор не найден. Попытка установки..."
    sudo pacman -S --needed --noconfirm base-devel gcc make sdl2 ffmpeg
fi

# 2. Компиляция
echo "[*] Компиляция..."
make clean
make

# 3. Настройка прав (udev)
echo "[*] Настройка udev..."
echo 'KERNEL=="hidg*", MODE="0666"' | sudo tee /etc/udev/rules.d/99-deckdisplay-hid.rules
sudo udevadm control --reload-rules && sudo udevadm trigger

# 4. Настройка сервиса
echo "[*] Настройка сервиса..."
sudo cp deckdisplay-gadget.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable deckdisplay-gadget.service
sudo systemctl restart deckdisplay-gadget.service

# 5. Исправление ярлыка (фиксируем путь)
echo "[*] Создание ярлыка..."
cat << EOF2 > ~/Desktop/DeckDisplay.desktop
[Desktop Entry]
Name=DeckDisplay Monitor
Exec=$(pwd)/launch_deckdisplay.sh
Icon=video-display
Terminal=false
Type=Application
EOF2
chmod +x ~/Desktop/DeckDisplay.desktop

echo "--- ГОТОВО! Запустите ярлык с рабочего стола ---"
