#!/bin/bash
# ==============================================================================
# DeckDisplay - Deployment Script for Decky Loader Plugin
# Deploys built plugin into /home/deck/homebrew/plugins/DeckDisplay
# Sets proper ownership and restarts plugin_loader.service
# ==============================================================================
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_PLUGIN_DIR="/home/deck/homebrew/plugins/DeckDisplay"

if [ "$EUID" -ne 0 ]; then
    echo "[DeckDisplay Decky] Требуются привилегии root для установки плагина."
    exec sudo bash "$0" "$@"
fi

if [ ! -f "$DIR/dist/index.js" ]; then
    echo "[Внимание] $DIR/dist/index.js не найден. Выполняем предварительную сборку..."
    bash "$DIR/build-plugin.sh"
fi

echo "[DeckDisplay Decky] Развертывание плагина в $TARGET_PLUGIN_DIR..."
mkdir -p "$TARGET_PLUGIN_DIR/dist"

cp "$DIR/plugin.json" "$TARGET_PLUGIN_DIR/"
cp "$DIR/main.py" "$TARGET_PLUGIN_DIR/"
cp "$DIR/package.json" "$TARGET_PLUGIN_DIR/"
cp "$DIR/dist/index.js" "$TARGET_PLUGIN_DIR/dist/"

# Для плагинов с root флагом в Decky Loader владелец обязан быть root:root
chown -R root:root "$TARGET_PLUGIN_DIR"
chmod -R 755 "$TARGET_PLUGIN_DIR"

echo "[DeckDisplay Decky] Перезапуск Decky Loader (plugin_loader.service)..."
systemctl restart plugin_loader.service || {
    echo "[Предупреждение] Не удалось перезапустить plugin_loader.service. Убедитесь, что Decky Loader установлен."
}

echo "[DeckDisplay Decky] Плагин успешно установлен и готов к использованию в Gaming Mode!"
