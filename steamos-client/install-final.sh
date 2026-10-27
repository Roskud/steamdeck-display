#!/bin/bash
set -e
echo "--- DeckDisplay: Финальная установка (без сбоев) ---"

# 1. Настройка быстрых зеркал (лечит ошибку "Operation too slow")
echo "[*] Настройка быстрых зеркал..."
sudo pacman -Sy --noconfirm reflector
sudo reflector --latest 5 --protocol https --sort rate --save /etc/pacman.d/mirrorlist

# 2. Установка зависимостей (только необходимое)
echo "[*] Установка зависимостей..."
sudo pacman -Sy --needed --noconfirm base-devel sdl2 ffmpeg dnsmasq

# 3. Компиляция
echo "[*] Компиляция..."
make clean
if ! make; then
    echo "[!] Ошибка компиляции. Убедитесь, что все зависимости установлены."
    exit 1
fi

# 4. Настройка прав (udev)
echo "[*] Настройка udev..."
echo 'KERNEL=="hidg*", MODE="0666"' | sudo tee /etc/udev/rules.d/99-deckdisplay-hid.rules
sudo udevadm control --reload-rules && sudo udevadm trigger

# 5. Настройка сервиса
echo "[*] Настройка сервиса..."
sudo cp deckdisplay-gadget.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable deckdisplay-gadget.service
sudo systemctl restart deckdisplay-gadget.service

# 6. Ярлык
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

echo "--- УСТАНОВКА УСПЕШНО ЗАВЕРШЕНА ---"
