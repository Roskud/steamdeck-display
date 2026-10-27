#!/bin/bash
# ==============================================================================
# DeckDisplay - Frontend Build Script for Decky Loader Plugin
# Installs Node.js dependencies and bundles src/index.tsx into dist/index.js
# ==============================================================================
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "[DeckDisplay Decky] Проверка Node.js и менеджера пакетов..."
if ! command -v node >/dev/null 2>&1; then
    echo "[DeckDisplay Decky] Node.js не найден. Установка через pacman..."
    sudo pacman -S --needed --noconfirm nodejs npm || {
        echo "[ОШИБКА] Не удалось установить Node.js. Установите его вручную."
        exit 1
    }
fi

PACKAGE_MANAGER="npm"
if command -v pnpm >/dev/null 2>&1; then
    PACKAGE_MANAGER="pnpm"
elif command -v npm >/dev/null 2>&1; then
    echo "[DeckDisplay Decky] Установка pnpm..."
    sudo npm install -g pnpm 2>/dev/null && PACKAGE_MANAGER="pnpm" || PACKAGE_MANAGER="npm"
fi

echo "[DeckDisplay Decky] Установка зависимостей через $PACKAGE_MANAGER..."
$PACKAGE_MANAGER install

echo "[DeckDisplay Decky] Сборка бандла Rollup (dist/index.js)..."
$PACKAGE_MANAGER run build

if [ -f "$DIR/dist/index.js" ]; then
    echo "[DeckDisplay Decky] Сборка успешно завершена! Файл создан: $DIR/dist/index.js"
else
    echo "[ОШИБКА] dist/index.js не был создан!"
    exit 1
fi
