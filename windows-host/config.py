# ==============================================================================
# DeckDisplay - Settings & System Configuration Manager
# Manages persistent JSON preferences and Windows Startup Registry integration.
# ==============================================================================

import json
import os
import sys
import winreg
from typing import Any, Dict

DEFAULT_SETTINGS: Dict[str, Any] = {
    "deck_ip": "10.77.77.2",
    "port": 5000,
    "output_idx": 0,               # Will be set to virtual display index if found
    "framerate": 90,              # 90 for OLED, 60 for LCD
    "encoder": "auto",            # auto, h264_nvenc, h264_amf, h264_qsv, libx264
    "bitrate": "45M",             # 45 Mbps
    "autostart": True,            # Auto-stream when Deck is detected
    "minimize_to_tray": True,     # Minimize to tray instead of closing
    "start_minimized": False,     # Start directly in tray
    "run_at_startup": False,      # Launch on Windows boot
    "notifications_enabled": True # Show system tray notifications
}

REGISTRY_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
REGISTRY_APP_NAME = "DeckDisplay"


def get_app_data_dir() -> str:
    app_data = os.environ.get("APPDATA")
    if not app_data:
        app_data = os.path.expanduser("~")
    target = os.path.join(app_data, "DeckDisplay")
    os.makedirs(target, exist_ok=True)
    return target


def get_settings_file_path() -> str:
    return os.path.join(get_app_data_dir(), "settings.json")


def load_settings() -> Dict[str, Any]:
    settings = DEFAULT_SETTINGS.copy()
    path = get_settings_file_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    settings.update(data)
        except Exception as e:
            print(f"[DeckDisplay Config] Error loading settings: {e}")
    settings["run_at_startup"] = is_run_at_startup_enabled()
    return settings


def save_settings(settings: Dict[str, Any]) -> bool:
    path = get_settings_file_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[DeckDisplay Config] Error saving settings: {e}")
        return False


def is_run_at_startup_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_RUN_KEY, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, REGISTRY_APP_NAME)
            return bool(val)
    except FileNotFoundError:
        return False
    except Exception:
        return False


def set_run_at_startup(enabled: bool, exe_path: str = None) -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                if not exe_path:
                    if getattr(sys, 'frozen', False):
                        exe_path = sys.executable
                    else:
                        exe_path = f'"{sys.executable}" "{os.path.abspath(os.path.join(os.path.dirname(__file__), "deckdisplay_app.py"))}"'
                
                # Add argument if we want it to start minimized
                cmd_value = f'"{exe_path}" --minimized' if not exe_path.startswith('"') else f'{exe_path} --minimized'
                winreg.SetValueEx(key, REGISTRY_APP_NAME, 0, winreg.REG_SZ, cmd_value)
            else:
                try:
                    winreg.DeleteValue(key, REGISTRY_APP_NAME)
                except FileNotFoundError:
                    pass
        return True
    except Exception as e:
        print(f"[DeckDisplay Config] Error updating startup registry: {e}")
        return False
