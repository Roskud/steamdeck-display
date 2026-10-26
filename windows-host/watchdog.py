# ==============================================================================
# DeckDisplay - Plug & Play Network Watchdog
# Automatically monitors Steam Deck USB-C connection, configures IP,
# and triggers auto-reconnect workflows.
# ==============================================================================

import subprocess
import threading
import time
from typing import Callable, Optional


def check_ping(ip: str, timeout_ms: int = 500) -> bool:
    """Checks if Steam Deck IP is reachable via ping."""
    try:
        # Use Windows ping with 1 echo and given timeout
        res = subprocess.run(
            ["ping", "-n", "1", "-w", str(timeout_ms), ip],
            capture_output=True,
            text=True,
            creationflags=0x08000000  # CREATE_NO_WINDOW
        )
        return res.returncode == 0
    except Exception:
        return False


def get_usb_ncm_adapter() -> Optional[str]:
    """Finds the network interface corresponding to Steam Deck UsbNcm / Remote NDIS."""
    try:
        ps_cmd = (
            "Get-NetAdapter -ErrorAction SilentlyContinue | "
            "Where-Object { ($_.InterfaceDescription -match 'UsbNcm|Remote NDIS|CDC|Steam Deck' -or $_.Name -match 'UsbNcm|Deck') -and $_.Status -eq 'Up' } | "
            "Select-Object -ExpandProperty Name -First 1"
        )
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            creationflags=0x08000000
        )
        out = res.stdout.strip()
        return out if out else None
    except Exception:
        return None


def is_adapter_ip_configured(adapter_name: str, expected_ip: str = "10.77.77.1") -> bool:
    """Checks if adapter already has the expected static IP assigned."""
    try:
        ps_cmd = f"(Get-NetIPAddress -InterfaceAlias '{adapter_name}' -AddressFamily IPv4 -ErrorAction SilentlyContinue).IPAddress"
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            creationflags=0x08000000
        )
        return expected_ip in res.stdout
    except Exception:
        return False


def configure_host_ip(adapter_name: str, host_ip: str = "10.77.77.1", netmask: str = "255.255.255.252") -> bool:
    """Configures static IP on the UsbNcm adapter without default gateway to preserve internet."""
    try:
        cmd = f'netsh interface ipv4 set address name="{adapter_name}" static {host_ip} {netmask} none'
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, creationflags=0x08000000)
        return res.returncode == 0
    except Exception:
        return False


class NetworkWatchdog:
    """Background thread that tracks connection to Steam Deck and handles plug & play."""

    def __init__(self, target_ip: str = "10.77.77.2"):
        self.target_ip: str = target_ip
        self.is_running: bool = False
        self.is_connected: bool = False
        self.thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Callbacks
        self.on_connected: Optional[Callable[[str], None]] = None
        self.on_disconnected: Optional[Callable[[], None]] = None
        self.on_log: Optional[Callable[[str], None]] = None

    def start(self) -> None:
        if self.is_running:
            return
        self.is_running = True
        self._stop_event.clear()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.is_running = False
        self._stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)

    def _run_loop(self) -> None:
        consecutive_failures = 0
        last_adapter_check = 0.0
        configured_adapters = set()

        while not self._stop_event.is_set():
            # 1. Periodic network adapter check and auto-config
            now = time.time()
            if now - last_adapter_check > 5.0:
                last_adapter_check = now
                adapter = get_usb_ncm_adapter()
                if adapter and adapter not in configured_adapters:
                    if not is_adapter_ip_configured(adapter):
                        if self.on_log:
                            self.on_log(f"[Watchdog] Обнаружен сетевой адаптер Steam Deck: {adapter}. Настройка IP 10.77.77.1...")
                        ok = configure_host_ip(adapter)
                        if ok:
                            configured_adapters.add(adapter)
                            if self.on_log:
                                self.on_log(f"[Watchdog] Интерфейс {adapter} успешно настроен (10.77.77.1/30).")
                        else:
                            if self.on_log:
                                self.on_log(f"[Watchdog] Внимание: не удалось настроить IP {adapter} автоматически. Запустите DeckDisplay от Администратора.")
                    else:
                        configured_adapters.add(adapter)

            # 2. Ping check
            is_alive = check_ping(self.target_ip, timeout_ms=600)

            if is_alive:
                consecutive_failures = 0
                if not self.is_connected:
                    self.is_connected = True
                    if self.on_log:
                        self.on_log(f"[Watchdog] Steam Deck доступен по адресу {self.target_ip}!")
                    if self.on_connected:
                        self.on_connected(self.target_ip)
            else:
                consecutive_failures += 1
                # Require 3 consecutive failures (approx 3-4s) before considering disconnected
                if consecutive_failures >= 3 and self.is_connected:
                    self.is_connected = False
                    configured_adapters.clear()  # reset cache on disconnect
                    if self.on_log:
                        self.on_log(f"[Watchdog] Соединение с {self.target_ip} потеряно (кабель отключен).")
                    if self.on_disconnected:
                        self.on_disconnected()

            self._stop_event.wait(1.0)
