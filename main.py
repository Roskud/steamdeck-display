# ==============================================================================
# DeckDisplay - Decky Loader Plugin Backend (Python)
# Manages USB ConfigFS gadget, low-latency video client, touch daemon,
# and background Plug & Play carrier monitoring.
# ==============================================================================

import asyncio
import json
import logging
import os
import signal
import subprocess
from typing import Any, Dict, Optional

# Совместимость с запуском вне Decky Loader для отладки и тестов
try:
    import decky
    logger = decky.logger
    SETTINGS_DIR = getattr(decky, "DECKY_PLUGIN_SETTINGS_DIR", "/home/deck/.config/deckdisplay")
except ImportError:
    class DummyDecky:
        DECKY_PLUGIN_SETTINGS_DIR = os.path.expanduser("~/.config/deckdisplay")
        @staticmethod
        async def emit(event: str, data: Any):
            pass
    decky = DummyDecky()
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("DeckDisplay")
    SETTINGS_DIR = decky.DECKY_PLUGIN_SETTINGS_DIR

BASE_DIR = os.environ.get("DECKDISPLAY_DIR", "/home/deck/deckdisplay/steamos-client")
GADGET_SCRIPT = os.path.join(BASE_DIR, "deckdisplay-gadget.sh")
CLEANUP_SCRIPT = os.path.join(BASE_DIR, "deckdisplay-cleanup.sh")
CLIENT_BIN = os.path.join(BASE_DIR, "deckdisplay_client")
TOUCH_BIN = os.path.join(BASE_DIR, "deckdisplay_touch")

GADGET_SYSFS = "/sys/kernel/config/usb_gadget/deckdisplay"
SETTINGS_FILE = os.path.join(SETTINGS_DIR, "settings.json")

DEFAULT_SETTINGS: Dict[str, Any] = {
    "udp_port": 5000,
    "fps": 90,
    "touch_enabled": True,
    "auto_plug_and_play": True,
    "auto_enable_gadget_on_boot": True,
}


class Plugin:
    def __init__(self):
        self.settings: Dict[str, Any] = DEFAULT_SETTINGS.copy()
        self.client_proc: Optional[subprocess.Popen] = None
        self.touch_proc: Optional[subprocess.Popen] = None
        self.monitor_task: Optional[asyncio.Task] = None
        self._last_carrier_state: bool = False

    # -------------------------------------------------------------------------
    # Управление настройками и файловой конфигурацией
    # -------------------------------------------------------------------------
    def _load_settings(self) -> None:
        try:
            os.makedirs(SETTINGS_DIR, exist_ok=True)
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self.settings.update(data)
        except Exception as e:
            logger.error(f"[DeckDisplay] Ошибка чтения настроек: {e}")

    def _save_settings(self) -> None:
        try:
            os.makedirs(SETTINGS_DIR, exist_ok=True)
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=2)
        except Exception as e:
            logger.error(f"[DeckDisplay] Ошибка сохранения настроек: {e}")

    # -------------------------------------------------------------------------
    # Системная телеметрия и проверка состояния оборудования
    # -------------------------------------------------------------------------
    def _is_gadget_active(self) -> bool:
        udc_file = os.path.join(GADGET_SYSFS, "UDC")
        if not os.path.exists(udc_file):
            return False
        try:
            with open(udc_file, "r", encoding="utf-8") as f:
                return len(f.read().strip()) > 0
        except OSError:
            return False

    def _get_udc_controller(self) -> str:
        udc_dir = "/sys/class/udc"
        if not os.path.exists(udc_dir):
            return "Не найден (требуется режим DRD в BIOS)"
        try:
            controllers = os.listdir(udc_dir)
            return controllers[0] if controllers else "Нет контроллера UDC"
        except OSError:
            return "Ошибка чтения UDC"

    def _is_usb_cable_connected(self) -> bool:
        # Проверяем наличие физического линка на виртуальном интерфейсе usb0
        for net_name in ["usb0", "ncm0"]:
            carrier_path = f"/sys/class/net/{net_name}/carrier"
            if os.path.exists(carrier_path):
                try:
                    with open(carrier_path, "r", encoding="utf-8") as f:
                        return f.read().strip() == "1"
                except OSError:
                    pass
        return False

    def _is_process_running(self, proc: Optional[subprocess.Popen], binary_name: str) -> bool:
        if proc is not None and proc.poll() is None:
            return True
        res = subprocess.run(["pgrep", "-f", binary_name], capture_output=True)
        return res.returncode == 0

    # -------------------------------------------------------------------------
    # Управление жизненным циклом демонов и видеоклиента
    # -------------------------------------------------------------------------
    def _start_touch_daemon(self) -> bool:
        if self._is_process_running(self.touch_proc, "deckdisplay_touch"):
            return True
        if not os.path.exists(TOUCH_BIN) or not os.path.exists("/dev/hidg0"):
            return False
        try:
            self.touch_proc = subprocess.Popen(
                [TOUCH_BIN, "/dev/hidg0"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                preexec_fn=os.setsid,
            )
            logger.info("[DeckDisplay] Демон сенсорного ввода запущен")
            return True
        except Exception as e:
            logger.error(f"[DeckDisplay] Ошибка запуска тачскрина: {e}")
            return False

    def _stop_touch_daemon(self) -> None:
        if self.touch_proc and self.touch_proc.poll() is None:
            try:
                os.killpg(os.getpgid(self.touch_proc.pid), signal.SIGTERM)
            except (ProcessLookupError, OSError):
                pass
        self.touch_proc = None
        subprocess.run(["pkill", "-f", "deckdisplay_touch"], capture_output=True)

    def _start_video_client(self) -> bool:
        if self._is_process_running(self.client_proc, "deckdisplay_client"):
            return True
        if not os.path.exists(CLIENT_BIN):
            logger.error(f"[DeckDisplay] Исполняемый файл не найден: {CLIENT_BIN}")
            return False

        port = int(self.settings.get("udp_port", 5000))
        url = f"udp://0.0.0.0:{port}?fifo_size=65536&overrun_nonfatal=1&timeout=200000"

        # Определение правильного сокета дисплея (Gaming Mode gamescope vs Desktop Mode)
        wayland_display = "gamescope-0"
        if not os.path.exists("/run/user/1000/gamescope-0"):
            if os.path.exists("/run/user/1000/wayland-0"):
                wayland_display = "wayland-0"

        # Запуск SDL2 клиента от имени пользователя deck (UID 1000) внутри сессии композитора
        env_vars = [
            "sudo", "-u", "deck",
            "env",
            "XDG_RUNTIME_DIR=/run/user/1000",
            f"WAYLAND_DISPLAY={wayland_display}",
            "DISPLAY=:0",
            "SDL_VIDEODRIVER=wayland,x11",
            CLIENT_BIN,
            url,
        ]
        try:
            self.client_proc = subprocess.Popen(
                env_vars,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                preexec_fn=os.setsid,
            )
            logger.info(f"[DeckDisplay] Видеоклиент запущен на порту {port} ({wayland_display})")
            return True
        except Exception as e:
            logger.error(f"[DeckDisplay] Ошибка запуска видеоклиента: {e}")
            return False

    def _stop_video_client(self) -> None:
        if self.client_proc and self.client_proc.poll() is None:
            try:
                os.killpg(os.getpgid(self.client_proc.pid), signal.SIGTERM)
            except (ProcessLookupError, OSError):
                pass
        self.client_proc = None
        subprocess.run(["pkill", "-f", "deckdisplay_client"], capture_output=True)

    def _collect_status(self) -> Dict[str, Any]:
        return {
            "gadget_active": self._is_gadget_active(),
            "udc_controller": self._get_udc_controller(),
            "usb_connected": self._is_usb_cable_connected(),
            "client_running": self._is_process_running(self.client_proc, "deckdisplay_client"),
            "touch_running": self._is_process_running(self.touch_proc, "deckdisplay_touch"),
            "deck_ip": "10.77.77.2",
            "host_ip": "10.77.77.1",
            "binaries_installed": os.path.exists(CLIENT_BIN) and os.path.exists(TOUCH_BIN),
            "settings": self.settings,
        }

    # -------------------------------------------------------------------------
    # Фоновый цикл Plug & Play и отправки телеметрии
    # -------------------------------------------------------------------------
    async def _status_monitor_loop(self) -> None:
        while True:
            try:
                status = self._collect_status()
                carrier_now = status["usb_connected"]

                # Логика Plug & Play при подключении/отключении USB-C кабеля
                if self.settings.get("auto_plug_and_play", True) and status["gadget_active"]:
                    if carrier_now and not self._last_carrier_state:
                        logger.info("[DeckDisplay] Кабель USB-C подключен! Автоматический старт дисплея...")
                        if self.settings.get("touch_enabled", True):
                            self._start_touch_daemon()
                        self._start_video_client()
                        status = self._collect_status()
                    elif not carrier_now and self._last_carrier_state:
                        logger.info("[DeckDisplay] Кабель USB-C отключен. Закрытие видеоклиента...")
                        self._stop_video_client()
                        self._stop_touch_daemon()
                        status = self._collect_status()

                self._last_carrier_state = carrier_now
                await decky.emit("deckdisplay_status", status)
            except Exception as e:
                logger.error(f"[DeckDisplay] Ошибка в цикле монитора: {e}")

            await asyncio.sleep(1.5)

    # -------------------------------------------------------------------------
    # RPC-методы, вызываемые фронтендом Decky (React UI)
    # -------------------------------------------------------------------------
    async def get_status(self) -> Dict[str, Any]:
        return self._collect_status()

    async def set_gadget_enabled(self, enabled: bool) -> Dict[str, Any]:
        script = GADGET_SCRIPT if enabled else CLEANUP_SCRIPT
        if not enabled:
            self._stop_video_client()
            self._stop_touch_daemon()

        if os.path.exists(script):
            res = subprocess.run([script], capture_output=True, text=True)
            if res.returncode != 0:
                logger.error(f"[DeckDisplay] Ошибка выполнения {script}: {res.stderr}")
        else:
            logger.error(f"[DeckDisplay] Скрипт не найден: {script}")

        return self._collect_status()

    async def set_stream_active(self, active: bool) -> Dict[str, Any]:
        if active:
            if not self._is_gadget_active():
                await self.set_gadget_enabled(True)
            if self.settings.get("touch_enabled", True):
                self._start_touch_daemon()
            self._start_video_client()
        else:
            self._stop_video_client()
            self._stop_touch_daemon()

        return self._collect_status()

    async def set_touch_enabled(self, enabled: bool) -> Dict[str, Any]:
        self.settings["touch_enabled"] = bool(enabled)
        self._save_settings()
        if enabled and self._is_gadget_active():
            self._start_touch_daemon()
        else:
            self._stop_touch_daemon()
        return self._collect_status()

    async def update_settings(self, new_settings: Dict[str, Any]) -> Dict[str, Any]:
        if isinstance(new_settings, dict):
            self.settings.update(new_settings)
            self._save_settings()
        return self._collect_status()

    # -------------------------------------------------------------------------
    # Жизненный цикл плагина Decky
    # -------------------------------------------------------------------------
    async def _main(self) -> None:
        logger.info("[DeckDisplay] Инициализация бэкенда плагина DeckDisplay...")
        self._load_settings()

        if self.settings.get("auto_enable_gadget_on_boot", True) and not self._is_gadget_active():
            if os.path.exists(GADGET_SCRIPT):
                subprocess.run([GADGET_SCRIPT], capture_output=True)

        self._last_carrier_state = self._is_usb_cable_connected()
        self.monitor_task = asyncio.ensure_future(self._status_monitor_loop())

    async def _unload(self) -> None:
        logger.info("[DeckDisplay] Выгрузка плагина...")
        if self.monitor_task:
            self.monitor_task.cancel()
        self._stop_video_client()
        self._stop_touch_daemon()

    async def _uninstall(self) -> None:
        await self._unload()
        if os.path.exists(CLEANUP_SCRIPT):
            subprocess.run([CLEANUP_SCRIPT], capture_output=True)
