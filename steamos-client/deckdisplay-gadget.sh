#!/bin/bash
# ==============================================================================
# DeckDisplay - USB ConfigFS Gadget Setup for Steam Deck (SteamOS)
# Configures USB-C port in Device mode (DRD), sets up CDC-NCM network adapter
# and HID Touchscreen Digitizer, and runs micro-DHCP server (dnsmasq).
# ==============================================================================
set -e

GADGET_NAME="deckdisplay"
GADGET_DIR="/sys/kernel/config/usb_gadget/$GADGET_NAME"
DECK_IP="10.77.77.2"
HOST_IP="10.77.77.1"
NETMASK="255.255.255.252"

echo "[DeckDisplay] Переключение контроллера USB-C в режим Device (DRD)..."

# 1. Принудительное переключение роли USB-контроллера AMD Van Gogh (dwc3)
shopt -s nullglob
for role_path in /sys/class/usb_role/*/role; do
    if [ -e "$role_path" ]; then
        echo "device" > "$role_path" 2>/dev/null || true
        echo "[DeckDisplay] Роль контроллера переключена через $role_path"
    fi
done
shopt -u nullglob

if [ -e /sys/kernel/debug/usb/dwc3.0.auto/mode ]; then
    echo "device" > /sys/kernel/debug/usb/dwc3.0.auto/mode 2>/dev/null || true
    echo "[DeckDisplay] DWC3 переведен в режим device"
fi

# 2. Загрузка необходимых модулей ядра Linux
modprobe configfs 2>/dev/null || true
modprobe libcomposite 2>/dev/null || true
modprobe usb_f_ncm 2>/dev/null || true
modprobe usb_f_hid 2>/dev/null || true

if [ ! -d /sys/kernel/config/usb_gadget ]; then
    mkdir -p /sys/kernel/config
    mount -t configfs none /sys/kernel/config 2>/dev/null || true
fi

# Очистка предыдущего экземпляра гаджета при необходимости
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -d "$GADGET_DIR" ]; then
    echo "[DeckDisplay] Обнаружен активный гаджет, выполняем очистку..."
    "$SCRIPT_DIR/deckdisplay-cleanup.sh" || true
fi

# 3. Создание композитного USB-гаджета
mkdir -p "$GADGET_DIR"
cd "$GADGET_DIR"

echo 0x1d6b > idVendor   # Linux Foundation
echo 0x0104 > idProduct  # Multifunction Composite Gadget
echo 0x0100 > bcdDevice  # v1.0.0
echo 0x0200 > bcdUSB     # USB 2.0 / USB 3.x совместимый дескриптор

# Коды интерфейса для Microsoft Windows IAD (Interface Association Descriptor)
echo 0xEF > bDeviceClass
echo 0x02 > bDeviceSubClass
echo 0x01 > bDeviceProtocol

mkdir -p strings/0x409
echo "SD-DISPLAY-001"           > strings/0x409/serialnumber
echo "Valve / DeckDisplay"      > strings/0x409/manufacturer
echo "Steam Deck Touch Monitor" > strings/0x409/product

# Microsoft OS Descriptors (для автоматического распознавания Windows 10/11)
echo 1       > os_desc/use
echo 0xcd    > os_desc/b_vendor_code
echo "MSFT100" > os_desc/qw_sign

# Создание конфигурации питания и дескрипторов
mkdir -p configs/c.1/strings/0x409
echo "CDC-NCM + HID Touch" > configs/c.1/strings/0x409/configuration
echo 500 > configs/c.1/MaxPower
ln -s configs/c.1 os_desc/c.1 2>/dev/null || true

# ------------------------------------------------------------------
# ФУНКЦИЯ 1: Виртуальный сетевой адаптер CDC-NCM (10 Гбит/с линк)
# ------------------------------------------------------------------
mkdir -p functions/ncm.usb0
echo "42:61:64:55:53:42" > functions/ncm.usb0/host_addr
echo "42:61:64:55:53:43" > functions/ncm.usb0/dev_addr
ln -s functions/ncm.usb0 configs/c.1/ 2>/dev/null || true

# ------------------------------------------------------------------
# ФУНКЦИЯ 2: USB HID Touchscreen Digitizer (16-bit, 0..32767)
# ------------------------------------------------------------------
mkdir -p functions/hid.usb0
echo 0 > functions/hid.usb0/protocol
echo 0 > functions/hid.usb0/subclass
echo 6 > functions/hid.usb0/report_length

# Дескриптор HID Single-Touch Digitizer (6 байт в репорте):
# Байт 0: Bit 0 = Tip Switch (касание), Bit 1 = In Range (в зоне действия)
# Байт 1..2: Координата X (0..32767, Little-Endian)
# Байт 3..4: Координата Y (0..32767, Little-Endian)
# Байт 5: Padding (0x00)
echo -ne '\x05\x0d\x09\x04\xa1\x01\x09\x22\xa1\x00\x09\x42\x09\x32\x15\x00\x25\x01\x75\x01\x95\x02\x81\x02\x95\x06\x81\x03\x05\x01\x09\x30\x09\x31\x16\x00\x00\x26\xff\x7f\x75\x10\x95\x02\x81\x02\x75\x08\x95\x01\x81\x03\xc0\xc0' > functions/hid.usb0/report_desc

ln -s functions/hid.usb0 configs/c.1/ 2>/dev/null || true

# ------------------------------------------------------------------
# Привязка к аппаратному UDC-контроллеру
# ------------------------------------------------------------------
UDC_DEV=$(ls /sys/class/udc 2>/dev/null | head -n 1)
if [ -z "$UDC_DEV" ]; then
    echo "[ОШИБКА] Не найден контроллер в /sys/class/udc!"
    echo "Проверьте настройки BIOS Steam Deck:"
    echo "  1. Выключите Deck, зажмите 'Volume +' и нажмите 'Power'"
    echo "  2. Перейдите в Setup Utility -> Advanced -> USB Configuration"
    echo "  3. Измените 'USB Dual Role Device' со значения XHCI на DRD"
    exit 1
fi

echo "$UDC_DEV" > UDC
sleep 1

# Ожидание создания узла /dev/hidg0 и сетевого интерфейса
for i in {1..10}; do
    if [ -e /dev/hidg0 ]; then
        chmod 0666 /dev/hidg0 || true
        break
    fi
    sleep 0.2
done

# Определение имени сетевого интерфейса (обычно usb0)
NET_IF=""
if [ -f functions/ncm.usb0/ifname ]; then
    NET_IF=$(cat functions/ncm.usb0/ifname)
fi
if [ -z "$NET_IF" ]; then
    NET_IF="usb0"
fi

# Настройка IP-адресации
ip link set "$NET_IF" up || true
ip addr flush dev "$NET_IF" || true
ip addr add "$DECK_IP/30" dev "$NET_IF"

# Запуск микро-DHCP сервера (dnsmasq) для автоматической выдачи IP компьютеру
# ВАЖНО: --dhcp-option=3 и 6 без аргументов запрещают выдавать шлюз и DNS,
# благодаря чему Windows НЕ теряет интернет-соединение через домашний Wi-Fi/Ethernet!
if command -v dnsmasq >/dev/null 2>&1; then
    pkill -f "dnsmasq.*deckdisplay" || true
    dnsmasq --interface="$NET_IF" \
            --bind-interfaces \
            --dhcp-range="$HOST_IP,$HOST_IP,$NETMASK,12h" \
            --dhcp-option=3 \
            --dhcp-option=6 \
            --pid-file=/run/deckdisplay-dnsmasq.pid
    echo "[DeckDisplay] DHCP-сервер запущен на интерфейсе $NET_IF (ПК получит $HOST_IP)"
fi

echo "[DeckDisplay] Гаджет успешно активирован! Сеть: $NET_IF ($DECK_IP), Тачскрин: /dev/hidg0"
