# ==============================================================================
# DeckDisplay - Windows Host Application
# Full-fledged Modern GUI with System Tray Integration for Windows 10/11.
# Provides automated Plug & Play streaming to Steam Deck (LCD & OLED).
# ==============================================================================

import ctypes
import os
import subprocess
import socket
import sys
import threading
import time
import tkinter as tk
from typing import Optional

import customtkinter as ctk
from PIL import Image

# Local modules
from config import (
    load_settings,
    save_settings,
    set_run_at_startup,
    is_run_at_startup_enabled,
    DEFAULT_SETTINGS
)
from engine import (
    StreamManager,
    detect_gpu_hardware,
    enumerate_displays,
    find_ffmpeg_binary
)
from watchdog import NetworkWatchdog
from tray import TrayManager


def get_resource_path(relative_path: str) -> str:
    """Gets absolute path to resource, works for dev, PyInstaller onefile, and standalone exe."""
    if hasattr(sys, '_MEIPASS'):
        p = os.path.join(sys._MEIPASS, relative_path)
        if os.path.exists(p):
            return p
    exe_dir = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))
    p = os.path.join(exe_dir, relative_path)
    if os.path.exists(p):
        return p
    parent_p = os.path.abspath(os.path.join(exe_dir, "..", relative_path))
    if os.path.exists(parent_p):
        return parent_p
    base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


class DeckDisplayApp(ctk.CTk):
    def __init__(self, start_minimized: bool = False):
        super().__init__()

        # 1. Load Configuration
        self.settings = load_settings()

        # 2. Window Setup
        self.title("DeckDisplay - Steam Deck Virtual Monitor")
        self.geometry("980x680")
        self.minsize(860, 600)
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")

        # Icons
        self.icon_ico_path = get_resource_path("icon.ico")
        self.icon_png_path = get_resource_path("icon.png")
        if os.path.exists(self.icon_ico_path):
            try:
                self.iconbitmap(self.icon_ico_path)
            except Exception:
                pass

        # Windows 10/11 Native Dark Titlebar
        self._enable_dark_titlebar()

        # 3. Core Engine & Managers
        self.stream_manager = StreamManager()
        self.stream_manager.on_metrics = self._on_stream_metrics_async
        self.stream_manager.on_status = self._on_stream_status_async
        self.stream_manager.on_log = self._log_message_async

        self.watchdog = NetworkWatchdog(target_ip=self.settings.get("deck_ip", "10.77.77.2"))
        self.watchdog.on_connected = self._on_deck_connected_async
        self.watchdog.on_disconnected = self._on_deck_disconnected_async
        self.watchdog.on_log = self._log_message_async

        # 4. System Tray Manager
        self.tray_manager = TrayManager(self.icon_png_path)
        self._init_tray_callbacks()

        # Telemetry State
        self.displays = enumerate_displays()
        self.detected_gpu_enc, self.gpu_name, self.gpu_desc = detect_gpu_hardware()
        self.ffmpeg_path = find_ffmpeg_binary()
        self._tray_tip_shown = False

        # 5. Build UI Layout
        self._build_header()
        self._build_tabs()
        self._build_footer()

        # Window Lifecycle
        self.protocol("WM_DELETE_WINDOW", self._on_window_close)
        self.bind("<Unmap>", self._on_window_unmap)

        # Start Services
        self.watchdog.start()
        self.tray_manager.start()

        # Initial Display Selection logic (pre-select virtual display if found)
        self._auto_select_virtual_display()

        self._log_message("[DeckDisplay] Приложение успешно запущено.")
        self._log_message(f"[Оборудование] Видеоадаптер: {self.gpu_name} ({self.detected_gpu_enc})")
        if self.ffmpeg_path:
            self._log_message(f"[FFmpeg] Обнаружен FFmpeg: {self.ffmpeg_path}")
        else:
            self._log_message("[FFmpeg] ВНИМАНИЕ: FFmpeg не найден! Используйте вкладку 'Журнал' для установки.")

        if start_minimized or self.settings.get("start_minimized", False):
            self.withdraw()
            self.tray_manager.set_status("idle", "DeckDisplay запущен в трее")
        
        self._start_udp_listener()

    def _start_udp_listener(self):
        def _listener():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                # Allow port reuse
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(('', 5001))
                self._log_message("[UDP] Слушатель запущен на порту 5001...")
                while True:
                    data, addr = sock.recvfrom(1024)
                    self._log_message(f"[UDP] Получен пакет от {addr}")
            except Exception as e:
                self._log_message(f"[UDP] Ошибка слушателя: {e}")
        
        threading.Thread(target=_listener, daemon=True).start()

    # -------------------------------------------------------------------------
    # UI Building
    # -------------------------------------------------------------------------
    def _build_header(self):
        self.header_frame = ctk.CTkFrame(self, fg_color="#131822", corner_radius=0, height=72)
        self.header_frame.pack(fill="x", padx=0, pady=0)
        self.header_frame.pack_propagate(False)

        # App Logo & Title
        title_box = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        title_box.pack(side="left", padx=20, pady=12)

        title_lbl = ctk.CTkLabel(
            title_box,
            text="🎮 DeckDisplay",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color="#ffffff"
        )
        title_lbl.pack(side="left", padx=(0, 10))

        sub_lbl = ctk.CTkLabel(
            title_box,
            text="Host v1.0",
            font=ctk.CTkFont(size=12),
            text_color="#00d2ff"
        )
        sub_lbl.pack(side="left", pady=(4, 0))

        # Status Pill
        self.status_pill = ctk.CTkLabel(
            self.header_frame,
            text="⚪ Ожидание подключения Steam Deck...",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#1f2736",
            text_color="#94a3b8",
            corner_radius=14,
            padx=14,
            pady=6
        )
        self.status_pill.pack(side="left", padx=20)

        # Right Action Area
        right_box = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        right_box.pack(side="right", padx=20, pady=12)

        self.btn_toggle_stream = ctk.CTkButton(
            right_box,
            text="▶ Начать трансляцию",
            command=self.toggle_stream,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#00b0ff",
            hover_color="#0081cb",
            text_color="#ffffff",
            height=38,
            width=180,
            corner_radius=8
        )
        self.btn_toggle_stream.pack(side="right")

    def _build_tabs(self):
        self.tabview = ctk.CTkTabview(
            self,
            fg_color="#18202d",
            segmented_button_fg_color="#0f141d",
            segmented_button_selected_color="#0081cb",
            segmented_button_selected_hover_color="#0069a3",
            corner_radius=8
        )
        self.tabview.pack(fill="both", expand=True, padx=16, pady=(10, 6))

        # Tabs
        self.tab_dashboard = self.tabview.add("📊 Мониторинг")
        self.tab_video = self.tabview.add("📺 Видео и экран")
        self.tab_tools = self.tabview.add("🛠️ Virtual Display и Тач")
        self.tab_logs = self.tabview.add("📝 Журнал событий")
        self.tab_settings = self.tabview.add("⚙️ Настройки")

        self._build_dashboard_tab()
        self._build_video_tab()
        self._build_tools_tab()
        self._build_logs_tab()
        self._build_settings_tab()

    # 1. Dashboard Tab
    def _build_dashboard_tab(self):
        container = ctk.CTkScrollableFrame(self.tab_dashboard, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=10, pady=10)

        # Telemetry Metrics Grid
        metrics_frame = ctk.CTkFrame(container, fg_color="#111620", corner_radius=10)
        metrics_frame.pack(fill="x", pady=(0, 14))

        m_title = ctk.CTkLabel(
            metrics_frame,
            text="Телеметрия передачи видео (Zero-Copy VRAM → UDP)",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#cbd5e1"
        )
        m_title.pack(anchor="w", padx=16, pady=(12, 8))

        grid = ctk.CTkFrame(metrics_frame, fg_color="transparent")
        grid.pack(fill="x", padx=14, pady=(0, 14))

        # 4 telemetry cards
        self.card_fps = self._create_stat_card(grid, "Фреймрейт", "0 FPS", "#00e676", 0)
        self.card_bitrate = self._create_stat_card(grid, "Битрейт", "0 Mbps", "#00d2ff", 1)
        self.card_speed = self._create_stat_card(grid, "Скорость энкодера", "1.00x", "#ffab00", 2)
        self.card_uptime = self._create_stat_card(grid, "Время трансляции", "00:00:00", "#e2e8f0", 3)

        # Connection & Link Card
        link_frame = ctk.CTkFrame(container, fg_color="#111620", corner_radius=10)
        link_frame.pack(fill="x", pady=(0, 14))

        l_title = ctk.CTkLabel(
            link_frame,
            text="Сетевое соединение и оборудование хоста",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#cbd5e1"
        )
        l_title.pack(anchor="w", padx=16, pady=(12, 8))

        self.lbl_deck_ip = ctk.CTkLabel(
            link_frame,
            text=f"• Адрес Steam Deck: {self.settings.get('deck_ip', '10.77.77.2')}:{self.settings.get('port', 5000)} (Порт UDP)",
            text_color="#94a3b8",
            font=ctk.CTkFont(size=13)
        )
        self.lbl_deck_ip.pack(anchor="w", padx=20, pady=2)

        self.lbl_gpu_info = ctk.CTkLabel(
            link_frame,
            text=f"• Видеокарта: {self.gpu_name} → {self.gpu_desc}",
            text_color="#94a3b8",
            font=ctk.CTkFont(size=13)
        )
        self.lbl_gpu_info.pack(anchor="w", padx=20, pady=2)

        self.lbl_display_target = ctk.CTkLabel(
            link_frame,
            text="• Захватываемый дисплей: Определение...",
            text_color="#94a3b8",
            font=ctk.CTkFont(size=13)
        )
        self.lbl_display_target.pack(anchor="w", padx=20, pady=2)

        self.lbl_link_status = ctk.CTkLabel(
            link_frame,
            text="• Кабель USB Type-C: Ожидание подключения...",
            text_color="#eab308",
            font=ctk.CTkFont(size=13, weight="bold")
        )
        self.lbl_link_status.pack(anchor="w", padx=20, pady=(2, 12))

    def _create_stat_card(self, parent, title: str, value: str, color: str, col: int) -> ctk.CTkLabel:
        card = ctk.CTkFrame(parent, fg_color="#18202d", corner_radius=8, width=200, height=80)
        card.grid(row=0, column=col, padx=6, pady=4, sticky="nsew")
        parent.grid_columnconfigure(col, weight=1)

        t_lbl = ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=11), text_color="#94a3b8")
        t_lbl.pack(anchor="w", padx=12, pady=(10, 2))

        val_lbl = ctk.CTkLabel(card, text=value, font=ctk.CTkFont(size=20, weight="bold"), text_color=color)
        val_lbl.pack(anchor="w", padx=12, pady=(0, 10))
        return val_lbl

    # 2. Video & Display Settings Tab
    def _build_video_tab(self):
        container = ctk.CTkScrollableFrame(self.tab_video, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=10, pady=10)

        # 1. Display Selector
        sec_disp = ctk.CTkFrame(container, fg_color="#111620", corner_radius=10)
        sec_disp.pack(fill="x", pady=(0, 14))

        ctk.CTkLabel(sec_disp, text="Выбор монитора для трансляции", font=ctk.CTkFont(size=14, weight="bold"), text_color="#cbd5e1").pack(anchor="w", padx=16, pady=(12, 6))
        ctk.CTkLabel(sec_disp, text="Для вывода рабочего стола без дублирования рекомендуется виртуальный дисплей 1280x800.", text_color="#94a3b8", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=16, pady=(0, 8))

        disp_labels = [d["label"] for d in self.displays]
        disp_row = ctk.CTkFrame(sec_disp, fg_color="transparent")
        disp_row.pack(fill="x", padx=16, pady=(0, 14))

        self.combo_displays = ctk.CTkComboBox(
            disp_row,
            values=disp_labels,
            width=520,
            command=self._on_display_selected,
            font=ctk.CTkFont(size=13)
        )
        self.combo_displays.pack(side="left", padx=(0, 10))

        ctk.CTkButton(
            disp_row,
            text="🔄 Обновить",
            width=100,
            command=self.refresh_display_list,
            fg_color="#1e293b",
            hover_color="#334155"
        ).pack(side="left")

        # 2. Framerate
        sec_fps = ctk.CTkFrame(container, fg_color="#111620", corner_radius=10)
        sec_fps.pack(fill="x", pady=(0, 14))

        ctk.CTkLabel(sec_fps, text="Частота кадров (FPS)", font=ctk.CTkFont(size=14, weight="bold"), text_color="#cbd5e1").pack(anchor="w", padx=16, pady=(12, 6))
        self.var_fps = ctk.IntVar(value=self.settings.get("framerate", 90))

        fps_row = ctk.CTkFrame(sec_fps, fg_color="transparent")
        fps_row.pack(anchor="w", padx=16, pady=(0, 14))

        ctk.CTkRadioButton(fps_row, text="90 FPS (Steam Deck OLED)", variable=self.var_fps, value=90, command=self._on_fps_changed).pack(side="left", padx=(0, 20))
        ctk.CTkRadioButton(fps_row, text="60 FPS (Steam Deck LCD)", variable=self.var_fps, value=60, command=self._on_fps_changed).pack(side="left", padx=(0, 20))
        ctk.CTkRadioButton(fps_row, text="120 FPS", variable=self.var_fps, value=120, command=self._on_fps_changed).pack(side="left")

        # 3. Hardware Encoder
        sec_enc = ctk.CTkFrame(container, fg_color="#111620", corner_radius=10)
        sec_enc.pack(fill="x", pady=(0, 14))

        ctk.CTkLabel(sec_enc, text="Аппаратный энкодер видео", font=ctk.CTkFont(size=14, weight="bold"), text_color="#cbd5e1").pack(anchor="w", padx=16, pady=(12, 6))

        self.var_enc = ctk.StringVar(value=self.settings.get("encoder", "auto"))
        enc_options = [
            f"Автовыбор: {self.detected_gpu_enc} (Рекомендуется)",
            "NVIDIA NVENC (h264_nvenc)",
            "AMD AMF (h264_amf)",
            "Intel QuickSync (h264_qsv)",
            "CPU Software (libx264)"
        ]
        self.combo_encoder = ctk.CTkComboBox(
            sec_enc,
            values=enc_options,
            width=400,
            command=self._on_encoder_selected
        )
        self.combo_encoder.pack(anchor="w", padx=16, pady=(0, 14))

        # 4. Bitrate
        sec_br = ctk.CTkFrame(container, fg_color="#111620", corner_radius=10)
        sec_br.pack(fill="x", pady=(0, 14))

        ctk.CTkLabel(sec_br, text="Битрейт передачи видео", font=ctk.CTkFont(size=14, weight="bold"), text_color="#cbd5e1").pack(anchor="w", padx=16, pady=(12, 6))

        br_row = ctk.CTkFrame(sec_br, fg_color="transparent")
        br_row.pack(anchor="w", padx=16, pady=(0, 14))

        self.var_bitrate = ctk.StringVar(value=self.settings.get("bitrate", "45M"))
        for br_val, br_label in [("25M", "25 Mbps"), ("35M", "35 Mbps"), ("45M", "45 Mbps (Рекомендуется)"), ("60M", "60 Mbps (Ultra)")]:
            ctk.CTkRadioButton(br_row, text=br_label, variable=self.var_bitrate, value=br_val, command=self._on_bitrate_changed).pack(side="left", padx=(0, 16))

    # 3. Virtual Display & Touch Tools Tab
    def _build_tools_tab(self):
        container = ctk.CTkScrollableFrame(self.tab_tools, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=10, pady=10)

        # Tool 1: Virtual Display Driver
        c1 = ctk.CTkFrame(container, fg_color="#111620", corner_radius=10)
        c1.pack(fill="x", pady=(0, 14))

        ctk.CTkLabel(c1, text="🖥️ Настройка виртуального монитора (IddCx)", font=ctk.CTkFont(size=15, weight="bold"), text_color="#cbd5e1").pack(anchor="w", padx=16, pady=(12, 4))
        ctk.CTkLabel(c1, text="Создает профиль C:\\IddSampleDriver\\option.txt с разрешением 1280x800 при 60 и 90 Гц.", text_color="#94a3b8", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=16, pady=(0, 10))

        btn_row1 = ctk.CTkFrame(c1, fg_color="transparent")
        btn_row1.pack(anchor="w", padx=16, pady=(0, 14))

        ctk.CTkButton(
            btn_row1,
            text="⚡ Настроить профиль 1280x800",
            command=self.run_virtual_display_setup,
            fg_color="#0284c7",
            hover_color="#0369a1"
        ).pack(side="left", padx=(0, 10))

        ctk.CTkButton(
            btn_row1,
            text="🌐 Скачать драйвер IddSampleDriver",
            command=lambda: os.startfile("https://github.com/itsmikethetech/Virtual-Display-Driver/releases"),
            fg_color="#334155",
            hover_color="#475569"
        ).pack(side="left")

        # Tool 2: Touch Calibration
        c2 = ctk.CTkFrame(container, fg_color="#111620", corner_radius=10)
        c2.pack(fill="x", pady=(0, 14))

        ctk.CTkLabel(c2, text="👆 Привязка сенсорного экрана (Калибровка Windows)", font=ctk.CTkFont(size=15, weight="bold"), text_color="#cbd5e1").pack(anchor="w", padx=16, pady=(12, 4))
        ctk.CTkLabel(
            c2,
            text="Если касания по дисплею Steam Deck нажимают на основном мониторе, выполните привязку:\n"
                 "1. Нажмите кнопку ниже.\n"
                 "2. Нажимайте клавишу Enter, пока белый экран не переместится на Steam Deck.\n"
                 "3. Один раз коснитесь экрана Steam Deck.",
            text_color="#94a3b8",
            font=ctk.CTkFont(size=12),
            justify="left"
        ).pack(anchor="w", padx=16, pady=(0, 10))

        ctk.CTkButton(
            c2,
            text="🎯 Запустить мастер калибровки Tablet PC",
            command=self.run_touch_calibration,
            fg_color="#0284c7",
            hover_color="#0369a1"
        ).pack(anchor="w", padx=16, pady=(0, 14))

    # 4. Logs Tab
    def _build_logs_tab(self):
        container = ctk.CTkFrame(self.tab_logs, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=10, pady=10)

        # Toolbar
        bar = ctk.CTkFrame(container, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 8))

        ctk.CTkButton(bar, text="Очистить", width=90, command=self._clear_logs).pack(side="left", padx=(0, 8))
        ctk.CTkButton(bar, text="Скопировать", width=110, command=self._copy_logs).pack(side="left", padx=(0, 8))
        ctk.CTkButton(bar, text="Установить актуальный FFmpeg через winget", command=self.run_install_ffmpeg).pack(side="right")

        self.txt_logs = ctk.CTkTextbox(
            container,
            font=ctk.CTkFont(family="Consolas", size=12),
            fg_color="#0d1117",
            text_color="#c9d1d9"
        )
        self.txt_logs.pack(fill="both", expand=True)

    # 5. App Settings Tab
    def _build_settings_tab(self):
        container = ctk.CTkScrollableFrame(self.tab_settings, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=10, pady=10)

        box = ctk.CTkFrame(container, fg_color="#111620", corner_radius=10)
        box.pack(fill="x", pady=(0, 14))

        ctk.CTkLabel(box, text="Интеграция с системой", font=ctk.CTkFont(size=15, weight="bold"), text_color="#cbd5e1").pack(anchor="w", padx=16, pady=(12, 6))

        # Minimize to tray toggle
        self.sw_min_tray = ctk.CTkSwitch(
            box,
            text="Сворачивать в системный трей при закрытии крестиком [X]",
            command=self._on_preference_changed
        )
        self.sw_min_tray.pack(anchor="w", padx=16, pady=8)
        if self.settings.get("minimize_to_tray", True):
            self.sw_min_tray.select()

        # Run at startup toggle
        self.sw_startup = ctk.CTkSwitch(
            box,
            text="Автозапуск при старте Windows (в системном трее)",
            command=self._on_startup_toggle
        )
        self.sw_startup.pack(anchor="w", padx=16, pady=8)
        if is_run_at_startup_enabled():
            self.sw_startup.select()

        # Auto-stream on connect
        self.sw_autostart = ctk.CTkSwitch(
            box,
            text="Автоматически начинать трансляцию при обнаружении кабеля Steam Deck",
            command=self._on_preference_changed
        )
        self.sw_autostart.pack(anchor="w", padx=16, pady=8)
        if self.settings.get("autostart", True):
            self.sw_autostart.select()

        # Network parameters
        net_box = ctk.CTkFrame(container, fg_color="#111620", corner_radius=10)
        net_box.pack(fill="x", pady=(0, 14))

        ctk.CTkLabel(net_box, text="Сетевые параметры Steam Deck", font=ctk.CTkFont(size=15, weight="bold"), text_color="#cbd5e1").pack(anchor="w", padx=16, pady=(12, 6))

        f_ip = ctk.CTkFrame(net_box, fg_color="transparent")
        f_ip.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(f_ip, text="IP-адрес консоли:", width=140, anchor="w").pack(side="left")
        self.entry_ip = ctk.CTkEntry(f_ip, width=200)
        self.entry_ip.insert(0, self.settings.get("deck_ip", "10.77.77.2"))
        self.entry_ip.pack(side="left")

        f_port = ctk.CTkFrame(net_box, fg_color="transparent")
        f_port.pack(fill="x", padx=16, pady=(4, 14))
        ctk.CTkLabel(f_port, text="Порт UDP:", width=140, anchor="w").pack(side="left")
        self.entry_port = ctk.CTkEntry(f_port, width=100)
        self.entry_port.insert(0, str(self.settings.get("port", 5000)))
        self.entry_port.pack(side="left")

        ctk.CTkButton(
            net_box,
            text="Сохранить сетевые настройки",
            command=self._save_network_settings,
            width=200
        ).pack(anchor="w", padx=16, pady=(0, 14))

        # Action: Exit application
        box_exit = ctk.CTkFrame(container, fg_color="#111620", corner_radius=10)
        box_exit.pack(fill="x", pady=(0, 14))

        ctk.CTkLabel(box_exit, text="Управление работой", font=ctk.CTkFont(size=15, weight="bold"), text_color="#cbd5e1").pack(anchor="w", padx=16, pady=(12, 4))
        ctk.CTkLabel(box_exit, text="Полное закрытие приложения (включая фоновый трей и вотчдог сети).", text_color="#94a3b8", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=16, pady=(0, 10))

        ctk.CTkButton(
            box_exit,
            text="❌ Завершить работу DeckDisplay",
            command=self.exit_application,
            fg_color="#dc2626",
            hover_color="#b91c1c",
            width=230
        ).pack(anchor="w", padx=16, pady=(0, 14))

    def _build_footer(self):
        footer = ctk.CTkFrame(self, fg_color="#0f141d", height=28, corner_radius=0)
        footer.pack(fill="x", side="bottom")

        self.lbl_footer = ctk.CTkLabel(
            footer,
            text="DeckDisplay • Готов к работе • Для сворачивания в трей просто закройте окно",
            font=ctk.CTkFont(size=11),
            text_color="#64748b"
        )
        self.lbl_footer.pack(side="left", padx=16)

    # -------------------------------------------------------------------------
    # System Tray Integration Callbacks
    # -------------------------------------------------------------------------
    def _init_tray_callbacks(self):
        self.tray_manager.on_show_window = lambda: self.after(0, self.restore_window)
        self.tray_manager.on_start_stream = lambda: self.after(0, self.start_stream)
        self.tray_manager.on_stop_stream = lambda: self.after(0, self.stop_stream)
        self.tray_manager.on_select_display = lambda idx: self.after(0, lambda: self._set_display_by_idx(idx))
        self.tray_manager.on_select_framerate = lambda fps: self.after(0, lambda: self._set_framerate(fps))
        self.tray_manager.on_setup_virtual_display = lambda: self.after(0, self.run_virtual_display_setup)
        self.tray_manager.on_calibrate_touch = lambda: self.after(0, self.run_touch_calibration)
        self.tray_manager.on_toggle_startup = lambda state: self.after(0, lambda: self._set_startup(state))
        self.tray_manager.on_exit = lambda: self.after(0, self.exit_application)

        # Dynamic state getters for tray menu
        self.tray_manager.is_streaming_getter = lambda: self.stream_manager.is_streaming
        self.tray_manager.startup_getter = is_run_at_startup_enabled
        self.tray_manager.displays_getter = lambda: self.displays
        self.tray_manager.framerate_getter = lambda: self.var_fps.get()

    def restore_window(self):
        self.deiconify()
        self.state("normal")
        self.attributes("-topmost", True)
        self.update()
        self.attributes("-topmost", False)
        self.lift()
        self.focus_force()

    def _on_window_close(self):
        if self.settings.get("minimize_to_tray", True):
            self.withdraw()
            if not self._tray_tip_shown:
                self.tray_manager.notify(
                    "DeckDisplay в системном трее",
                    "Приложение свернуто и продолжает работу в трее. Кликните по иконке для открытия."
                )
                self._tray_tip_shown = True
        else:
            self.exit_application()

    def _on_window_unmap(self, event):
        # Allow minimizing to tray on regular minimize button if desired
        pass

    def exit_application(self):
        self._log_message("[DeckDisplay] Завершение работы...")
        self.watchdog.stop()
        self.stream_manager.stop_stream()
        self.tray_manager.stop()
        self.destroy()
        sys.exit(0)

    # -------------------------------------------------------------------------
    # Streaming Workflow
    # -------------------------------------------------------------------------
    def toggle_stream(self):
        if self.stream_manager.is_streaming:
            self.stop_stream()
        else:
            self.start_stream()

    def start_stream(self):
        deck_ip = self.settings.get("deck_ip", "10.77.77.2")
        port = int(self.settings.get("port", 5000))
        output_idx = int(self.settings.get("output_idx", 0))
        framerate = int(self.var_fps.get())
        encoder = self.settings.get("encoder", "auto")
        bitrate = self.settings.get("bitrate", "45M")

        ok, msg = self.stream_manager.start_stream(deck_ip, port, output_idx, framerate, encoder, bitrate)
        if ok:
            self.btn_toggle_stream.configure(
                text="⏹ Остановить",
                fg_color="#ef4444",
                hover_color="#dc2626"
            )
            self.status_pill.configure(
                text=f"🟢 В эфире: {deck_ip}:{port} ({framerate} FPS)",
                fg_color="#064e3b",
                text_color="#34d399"
            )
            self.tray_manager.set_status("streaming", f"DeckDisplay: В эфире ({deck_ip}:{port})")
            if self.settings.get("notifications_enabled", True):
                self.tray_manager.notify("Трансляция запущена", f"Поток 1280x800 @ {framerate} FPS передан на {deck_ip}")
        else:
            self._log_message(f"[Ошибка] {msg}")

    def stop_stream(self):
        self.stream_manager.stop_stream()
        self.btn_toggle_stream.configure(
            text="▶ Начать трансляцию",
            fg_color="#00b0ff",
            hover_color="#0081cb"
        )
        if self.watchdog.is_connected:
            self.status_pill.configure(
                text="🟢 Steam Deck подключен",
                fg_color="#0f291e",
                text_color="#4ade80"
            )
            self.tray_manager.set_status("waiting", "DeckDisplay: Подключен (ожидание старта)")
        else:
            self.status_pill.configure(
                text="⚪ Ожидание подключения Steam Deck...",
                fg_color="#1f2736",
                text_color="#94a3b8"
            )
            self.tray_manager.set_status("idle", "DeckDisplay: Ожидание подключения")

        # Reset metric cards
        self.card_fps.configure(text="0 FPS")
        self.card_bitrate.configure(text="0 Mbps")

    # -------------------------------------------------------------------------
    # Asynchronous Callbacks (Watchdog, Engine -> GUI Thread)
    # -------------------------------------------------------------------------
    def _on_deck_connected_async(self, ip: str):
        self.after(0, lambda: self._on_deck_connected(ip))

    def _on_deck_connected(self, ip: str):
        self.lbl_link_status.configure(
            text=f"• Кабель USB Type-C: Подключен! IP: {ip}",
            text_color="#00e676"
        )
        if not self.stream_manager.is_streaming:
            self.status_pill.configure(
                text="🟢 Steam Deck подключен",
                fg_color="#0f291e",
                text_color="#4ade80"
            )
            self.tray_manager.set_status("waiting", f"Steam Deck подключен ({ip})")
            if self.settings.get("notifications_enabled", True):
                self.tray_manager.notify("Steam Deck подключен", f"Обнаружена консоль по кабелю ({ip})")

            # Auto-start stream if enabled
            if self.settings.get("autostart", True):
                self._log_message("[Plug & Play] Автоматический запуск трансляции...")
                self.start_stream()

    def _on_deck_disconnected_async(self):
        self.after(0, self._on_deck_disconnected)

    def _on_deck_disconnected(self):
        self.lbl_link_status.configure(
            text="• Кабель USB Type-C: Отключен",
            text_color="#eab308"
        )
        if self.stream_manager.is_streaming:
            self._log_message("[Watchdog] Кабель отключен, остановка трансляции...")
            self.stop_stream()

        self.status_pill.configure(
            text="⚪ Ожидание подключения Steam Deck...",
            fg_color="#1f2736",
            text_color="#94a3b8"
        )
        self.tray_manager.set_status("idle", "DeckDisplay: Ожидание подключения")
        if self.settings.get("notifications_enabled", True):
            self.tray_manager.notify("Кабель отключен", "Steam Deck отсоединен от ПК")

    def _on_stream_metrics_async(self, fps: int, bitrate: str, speed: float, frames: int, uptime: float):
        self.after(0, lambda: self._update_stream_metrics(fps, bitrate, speed, frames, uptime))

    def _update_stream_metrics(self, fps: int, bitrate: str, speed: float, frames: int, uptime: float):
        self.card_fps.configure(text=f"{fps} FPS")
        self.card_bitrate.configure(text=bitrate)
        self.card_speed.configure(text=f"{speed:.2f}x")

        hrs = int(uptime // 3600)
        mins = int((uptime % 3600) // 60)
        secs = int(uptime % 60)
        self.card_uptime.configure(text=f"{hrs:02d}:{mins:02d}:{secs:02d}")

    def _on_stream_status_async(self, is_running: bool, message: str):
        self.after(0, lambda: self._log_message(f"[Статус потока] {message}"))

    def _log_message_async(self, text: str):
        self.after(0, lambda: self._log_message(text))

    def _log_message(self, text: str):
        ts = time.strftime("%H:%M:%S")
        entry = f"[{ts}] {text}\n"
        try:
            self.txt_logs.insert("end", entry)
            self.txt_logs.see("end")
        except Exception:
            pass

    def _clear_logs(self):
        self.txt_logs.delete("1.0", "end")

    def _copy_logs(self):
        logs = self.txt_logs.get("1.0", "end")
        self.clipboard_clear()
        self.clipboard_append(logs)
        self._log_message("[Журнал] Скопирован в буфер обмена.")

    # -------------------------------------------------------------------------
    # Helper & Tool Launchers
    # -------------------------------------------------------------------------
    def _auto_select_virtual_display(self):
        saved_idx = self.settings.get("output_idx", None)
        if saved_idx is not None and 0 <= saved_idx < len(self.displays):
            self._set_display_by_idx(saved_idx)
            return

        target_idx = 0
        for d in self.displays:
            if d.get("is_virtual"):
                target_idx = d["idx"]
                break
            elif not d.get("is_primary") and len(self.displays) > 1:
                target_idx = d["idx"]

        self._set_display_by_idx(target_idx)

    def refresh_display_list(self):
        """Re-scans connected monitors and updates UI and tray menus."""
        self.displays = enumerate_displays()
        disp_labels = [d["label"] for d in self.displays]
        self.combo_displays.configure(values=disp_labels)
        current_idx = self.settings.get("output_idx", 0)
        if current_idx < len(self.displays):
            self.combo_displays.set(self.displays[current_idx]["label"])
            self.lbl_display_target.configure(
                text=f"• Захватываемый дисплей: {self.displays[current_idx]['label']}"
            )
        elif self.displays:
            self._set_display_by_idx(0)
        self.tray_manager.update_menu()
        self._log_message(f"[Дисплеи] Список мониторов обновлен (найдено: {len(self.displays)}).")

    def _set_display_by_idx(self, idx: int):
        if idx < len(self.displays):
            d = self.displays[idx]
            self.settings["output_idx"] = idx
            save_settings(self.settings)
            self.combo_displays.set(d["label"])
            self.lbl_display_target.configure(
                text=f"• Захватываемый дисплей: {d['label']}"
            )
            self.tray_manager.update_menu()

    def _on_display_selected(self, choice: str):
        for d in self.displays:
            if d["label"] == choice:
                self._set_display_by_idx(d["idx"])
                break

    def _on_fps_changed(self):
        fps = self.var_fps.get()
        self.settings["framerate"] = fps
        save_settings(self.settings)
        self._log_message(f"[Настройки] Частота кадров установлена: {fps} FPS")
        self.tray_manager.update_menu()

    def _set_framerate(self, fps: int):
        self.var_fps.set(fps)
        self._on_fps_changed()

    def _on_encoder_selected(self, choice: str):
        if "NVENC" in choice:
            enc = "h264_nvenc"
        elif "AMF" in choice:
            enc = "h264_amf"
        elif "QuickSync" in choice:
            enc = "h264_qsv"
        elif "CPU" in choice:
            enc = "libx264"
        else:
            enc = "auto"

        self.settings["encoder"] = enc
        save_settings(self.settings)
        self._log_message(f"[Настройки] Видеокодер: {enc}")

    def _on_bitrate_changed(self):
        br = self.var_bitrate.get()
        self.settings["bitrate"] = br
        save_settings(self.settings)
        self._log_message(f"[Настройки] Битрейт: {br}")

    def _on_preference_changed(self):
        self.settings["minimize_to_tray"] = bool(self.sw_min_tray.get())
        self.settings["autostart"] = bool(self.sw_autostart.get())
        save_settings(self.settings)

    def _on_startup_toggle(self):
        enabled = bool(self.sw_startup.get())
        self._set_startup(enabled)

    def _set_startup(self, enabled: bool):
        set_run_at_startup(enabled)
        if enabled:
            self.sw_startup.select()
            self._log_message("[Настройки] Автозапуск с Windows включен.")
        else:
            self.sw_startup.deselect()
            self._log_message("[Настройки] Автозапуск с Windows отключен.")
        self.tray_manager.update_menu()

    def _save_network_settings(self):
        ip = self.entry_ip.get().strip()
        try:
            port = int(self.entry_port.get().strip())
        except ValueError:
            port = 5000

        self.settings["deck_ip"] = ip
        self.settings["port"] = port
        save_settings(self.settings)
        self.watchdog.target_ip = ip
        self.lbl_deck_ip.configure(text=f"• Адрес Steam Deck: {ip}:{port} (Порт UDP)")
        self._log_message(f"[Настройки] Сетевой адрес обновлен: {ip}:{port}")

    def run_virtual_display_setup(self):
        self._log_message("[Setup] Настройка виртуального монитора (IddCx)...")
        target_dir = r"C:\IddSampleDriver"
        target_file = os.path.join(target_dir, "option.txt")
        profile_content = "1\n1280, 800, 60\n1280, 800, 90\n"

        try:
            os.makedirs(target_dir, exist_ok=True)
            with open(target_file, "w", encoding="ascii") as f:
                f.write(profile_content)
            self._log_message(f"[Setup] Профиль 1280x800 @ 60/90Hz успешно сохранен в {target_file}")
        except PermissionError:
            self._log_message("[Setup] Доступ ограничен, запуск сохранения с правами Администратора...")
            try:
                ps_cmd = f"Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile -Command New-Item -ItemType Directory -Path \"{target_dir}\" -Force; Set-Content -Path \"{target_file}\" -Value @(\\\"1\\\", \\\"1280, 800, 60\\\", \\\"1280, 800, 90\\\")'"
                subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], creationflags=0x08000000)
            except Exception as ex:
                self._log_message(f"[Ошибка] Не удалось создать профиль: {ex}")
        except Exception as e:
            self._log_message(f"[Ошибка] Запись option.txt: {e}")

        # Check driver device in background and refresh displays
        threading.Thread(target=self._check_idd_device_status, daemon=True).start()

    def _check_idd_device_status(self):
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Get-PnpDevice -FriendlyName '*Virtual Display*' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Status -First 1"],
                capture_output=True, text=True, timeout=5, creationflags=0x08000000
            )
            status = res.stdout.strip()
            if status:
                self._log_message_async(f"[Setup] Виртуальный дисплей обнаружен в системе (Статус: {status}).")
                time.sleep(1.0)
                self.after(0, self.refresh_display_list)
            else:
                self._log_message_async("[Setup] Драйвер IddSampleDriver еще не установлен в диспетчере устройств.")
                self._log_message_async("[Setup] Нажмите 'Скачать драйвер IddSampleDriver', распакуйте в C:\\IddSampleDriver и запустите Install.bat.")
        except Exception as e:
            self._log_message_async(f"[Setup] Примечание по проверке PnP: {e}")

    def run_touch_calibration(self):
        self._log_message("[Калибровка] Запуск системного мастера Tablet PC (control tabletpc.cpl)...")
        try:
            subprocess.Popen(["control.exe", "tabletpc.cpl"], shell=True)
            self._log_message("[Калибровка] В открывшемся окне нажмите 'Настройка...', нажимайте Enter до перехода на экран Deck, и коснитесь экрана.")
        except Exception as e:
            self._log_message(f"[Ошибка] Запуск калибровки Tablet PC: {e}")

    def run_install_ffmpeg(self):
        self._log_message("[FFmpeg] Запуск установки Gyan.FFmpeg через winget...")
        threading.Thread(target=self._exec_install_ffmpeg, daemon=True).start()

    def _exec_install_ffmpeg(self):
        try:
            p = subprocess.Popen(
                ["winget", "install", "Gyan.FFmpeg", "--accept-package-agreements", "--accept-source-agreements"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=0x08000000
            )
            for line in p.stdout:
                line_str = line.strip()
                if line_str:
                    self._log_message_async(f"[FFmpeg Setup] {line_str}")
            p.wait()
            # Refresh path
            self.ffmpeg_path = find_ffmpeg_binary()
            if self.ffmpeg_path:
                self._log_message_async(f"[FFmpeg Setup] Успешно! Актуальный путь к FFmpeg: {self.ffmpeg_path}")
            else:
                self._log_message_async("[FFmpeg Setup] Установка завершена. Если FFmpeg не определился сразу, перезапустите приложение.")
        except Exception as e:
            self._log_message_async(f"[Ошибка установки FFmpeg] {e}")

    def _enable_dark_titlebar(self):
        """Enables Windows 10 / 11 native dark mode for the window frame."""
        try:
            self.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            # DWMWA_USE_IMMERSIVE_DARK_MODE (20 on Win11 / Win10 20H1+, 19 on older Win10)
            DWMWA_USE_IMMERSIVE_DARK_MODE = 20
            val = ctypes.c_int(1)
            res = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd,
                DWMWA_USE_IMMERSIVE_DARK_MODE,
                ctypes.byref(val),
                ctypes.sizeof(val)
            )
            if res != 0:
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, 19, ctypes.byref(val), ctypes.sizeof(val)
                )
        except Exception:
            pass


def main():
    start_minimized = "--minimized" in sys.argv
    app = DeckDisplayApp(start_minimized=start_minimized)
    app.mainloop()


if __name__ == "__main__":
    main()
