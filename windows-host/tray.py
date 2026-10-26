# ==============================================================================
# DeckDisplay - System Tray (Notification Area) Manager
# Provides seamless taskbar tray integration, dynamic status icons,
# contextual menus, and native Windows notifications using pystray.
# ==============================================================================

import os
import threading
from typing import Callable, Dict, List, Optional
from PIL import Image, ImageDraw
import pystray
from pystray import MenuItem as item


class TrayManager:
    """Manages the Windows System Tray icon, menu, and notifications."""

    def __init__(self, icon_path: Optional[str] = None):
        if not icon_path:
            import sys
            base_dir = getattr(sys, '_MEIPASS', os.path.dirname(__file__))
            self.icon_path = os.path.join(base_dir, "icon.png")
        else:
            self.icon_path = icon_path
        self.base_image: Image.Image = self._load_base_image()
        self.current_status: str = "idle"  # "idle", "waiting", "streaming"
        self.icon: Optional[pystray.Icon] = None
        self.thread: Optional[threading.Thread] = None

        # Callbacks hooked by the GUI application
        self.on_show_window: Optional[Callable[[], None]] = None
        self.on_start_stream: Optional[Callable[[], None]] = None
        self.on_stop_stream: Optional[Callable[[], None]] = None
        self.on_select_display: Optional[Callable[[int], None]] = None
        self.on_select_framerate: Optional[Callable[[int], None]] = None
        self.on_setup_virtual_display: Optional[Callable[[], None]] = None
        self.on_calibrate_touch: Optional[Callable[[], None]] = None
        self.on_toggle_startup: Optional[Callable[[bool], None]] = None
        self.on_exit: Optional[Callable[[], None]] = None

        # Dynamic state providers
        self.is_streaming_getter: Callable[[], bool] = lambda: False
        self.startup_getter: Callable[[], bool] = lambda: False
        self.displays_getter: Callable[[], List[Dict]] = lambda: []
        self.framerate_getter: Callable[[], int] = lambda: 90

    def _load_base_image(self) -> Image.Image:
        if os.path.exists(self.icon_path):
            try:
                return Image.open(self.icon_path).convert("RGBA").resize((64, 64), Image.Resampling.LANCZOS)
            except Exception:
                pass

        # Fallback generated base image
        img = Image.new("RGBA", (64, 64), (16, 24, 38, 255))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([4, 4, 60, 60], radius=12, fill=(18, 26, 42, 255), outline=(0, 210, 255, 255), width=2)
        return img

    def get_status_image(self, status: str) -> Image.Image:
        """Draws a status dot overlay on the base tray icon."""
        img = self.base_image.copy()
        draw = ImageDraw.Draw(img)

        # Status dot colors
        colors = {
            "streaming": (0, 230, 118, 255),   # Green
            "waiting":   (255, 171, 0, 255),   # Amber/Yellow
            "idle":      (120, 140, 160, 255)  # Gray/Blue
        }
        color = colors.get(status, (120, 140, 160, 255))

        # Bottom-right badge
        dot_r = 9
        cx = 64 - dot_r - 2
        cy = 64 - dot_r - 2

        # Outer ring
        draw.ellipse([cx - dot_r - 1, cy - dot_r - 1, cx + dot_r + 1, cy + dot_r + 1], fill=(10, 15, 24, 255))
        # Inner dot
        draw.ellipse([cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r], fill=color)

        return img

    def _build_menu(self) -> pystray.Menu:
        """Constructs the system tray context menu dynamically."""
        is_streaming = self.is_streaming_getter()
        is_startup = self.startup_getter()
        current_fps = self.framerate_getter()
        displays = self.displays_getter()

        # Display selection sub-menu
        display_items = []
        for d in displays:
            idx = d.get("idx", 0)
            lbl = d.get("label", f"Дисплей #{idx}")
            display_items.append(
                item(lbl, lambda _, i=idx: self.on_select_display and self.on_select_display(i))
            )
        display_menu = pystray.Menu(*display_items) if display_items else None

        # Framerate sub-menu
        fps_menu = pystray.Menu(
            item("90 FPS (Steam Deck OLED)", lambda _: self.on_select_framerate and self.on_select_framerate(90), checked=lambda _: current_fps == 90),
            item("60 FPS (Steam Deck LCD)", lambda _: self.on_select_framerate and self.on_select_framerate(60), checked=lambda _: current_fps == 60),
            item("120 FPS (High Refresh)", lambda _: self.on_select_framerate and self.on_select_framerate(120), checked=lambda _: current_fps == 120),
        )

        menu_items = [
            item("🎮 DeckDisplay v1.0", None, enabled=False),
            pystray.Menu.SEPARATOR,
            item(
                "⏹️ Остановить трансляцию" if is_streaming else "▶️ Начать трансляцию",
                self._toggle_stream_action
            ),
            item("🖥️ Показать окно", self._show_window_action, default=True),
            pystray.Menu.SEPARATOR,
        ]

        if display_menu:
            menu_items.append(item("📺 Выбор монитора", display_menu))

        menu_items.extend([
            item("⚡ Частота кадров", fps_menu),
            pystray.Menu.SEPARATOR,
            item("🛠️ Настройка Virtual Display", lambda _: self.on_setup_virtual_display and self.on_setup_virtual_display()),
            item("👆 Калибровка тачскрина", lambda _: self.on_calibrate_touch and self.on_calibrate_touch()),
            pystray.Menu.SEPARATOR,
            item("🚀 Автозапуск с Windows", self._toggle_startup_action, checked=lambda _: is_startup),
            item("❌ Выход", self._exit_action)
        ])

        return pystray.Menu(*menu_items)

    def _show_window_action(self, icon=None, item_obj=None) -> None:
        if self.on_show_window:
            self.on_show_window()

    def _toggle_stream_action(self, icon=None, item_obj=None) -> None:
        if self.is_streaming_getter():
            if self.on_stop_stream:
                self.on_stop_stream()
        else:
            if self.on_start_stream:
                self.on_start_stream()

    def _toggle_startup_action(self, icon=None, item_obj=None) -> None:
        new_state = not self.startup_getter()
        if self.on_toggle_startup:
            self.on_toggle_startup(new_state)
        self.update_menu()

    def _exit_action(self, icon=None, item_obj=None) -> None:
        if self.on_exit:
            self.on_exit()

    def start(self) -> None:
        """Starts the tray icon in background detached mode."""
        if self.icon:
            return

        img = self.get_status_image("idle")
        self.icon = pystray.Icon(
            name="DeckDisplay",
            icon=img,
            title="DeckDisplay - Второй монитор для ПК",
            menu=self._build_menu()
        )
        self.icon.run_detached()

    def set_status(self, status: str, tooltip: str = "") -> None:
        """Updates tray icon badge and tooltip."""
        self.current_status = status
        if self.icon:
            self.icon.icon = self.get_status_image(status)
            if tooltip:
                self.icon.title = tooltip[:127]
            self.icon.menu = self._build_menu()

    def update_menu(self) -> None:
        """Refreshes the tray menu items."""
        if self.icon:
            self.icon.menu = self._build_menu()

    def notify(self, title: str, message: str) -> None:
        """Displays a native Windows toast/balloon notification."""
        if self.icon:
            try:
                self.icon.notify(message, title)
            except Exception as e:
                print(f"[DeckDisplay Tray] Notification error: {e}")

    def stop(self) -> None:
        """Stops the tray icon."""
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass
            self.icon = None
