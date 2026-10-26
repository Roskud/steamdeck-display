#!/bin/bash
# ==============================================================================
# DeckDisplay - Safe USB ConfigFS Gadget Teardown for SteamOS
# Unbinds the UDC controller, destroys ConfigFS nodes, and stops DHCP.
# ==============================================================================

GADGET_NAME="deckdisplay"
GADGET_DIR="/sys/kernel/config/usb_gadget/$GADGET_NAME"

# Остановка микро-DHCP сервера
if [ -f /run/deckdisplay-dnsmasq.pid ]; then
    kill "$(cat /run/deckdisplay-dnsmasq.pid)" 2>/dev/null || true
    rm -f /run/deckdisplay-dnsmasq.pid
fi
pkill -f "dnsmasq.*deckdisplay" 2>/dev/null || true

if [ ! -d "$GADGET_DIR" ]; then
    echo "[DeckDisplay] Гаджет $GADGET_NAME не смонтирован."
    exit 0
fi

cd "$GADGET_DIR"

# 1. Отвязка UDC-контроллера (критично выждать паузу перед удалением линков)
echo "" > UDC 2>/dev/null || true
sleep 0.5

# 2. Удаление символических ссылок функций
rm -f os_desc/c.1 2>/dev/null || true
rm -f configs/c.1/ncm.usb0 2>/dev/null || true
rm -f configs/c.1/hid.usb0 2>/dev/null || true

# 3. Удаление каталогов конфигурации и функций в обратном порядке
rmdir configs/c.1/strings/0x409 2>/dev/null || true
rmdir configs/c.1 2>/dev/null || true
rmdir functions/ncm.usb0 2>/dev/null || true
rmdir functions/hid.usb0 2>/dev/null || true
rmdir strings/0x409 2>/dev/null || true

cd /
rmdir "$GADGET_DIR" 2>/dev/null || true

echo "[DeckDisplay] USB-гаджет успешно выгружен."
