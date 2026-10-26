# ==============================================================================
# DeckDisplay - Streaming Engine & Hardware Controller
# Handles DXGI Desktop Duplication capture (ddagrab), GPU encoder selection,
# display discovery, and real-time streaming process lifecycle.
# ==============================================================================

import glob
import os
import re
import shutil
import subprocess
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple


def find_ffmpeg_binary() -> Optional[str]:
    """Finds modern FFmpeg with ddagrab support."""
    # 1. LocalAppData WinGet packages (most common for Gyan.FFmpeg)
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    candidates = []
    if local_app_data:
        winget_pattern = os.path.join(local_app_data, "Microsoft", "WinGet", "Packages", "Gyan.FFmpeg*")
        for match in glob.glob(winget_pattern):
            for root, dirs, files in os.walk(match):
                if "ffmpeg.exe" in files:
                    candidates.append(os.path.join(root, "ffmpeg.exe"))

    # 2. PATH executables
    which_all = []
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-Command -All ffmpeg -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source"],
            capture_output=True, text=True, timeout=3
        )
        for line in res.stdout.splitlines():
            line = line.strip()
            if line and os.path.exists(line):
                which_all.append(line)
    except Exception:
        pass

    candidates.extend(which_all)

    # 3. Standard installation paths
    common_paths = [
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\tools\ffmpeg\bin\ffmpeg.exe",
        r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
    ]
    candidates.extend([p for p in common_paths if os.path.exists(p)])

    # Check each candidate for ddagrab filter
    for exe in candidates:
        try:
            r = subprocess.run([exe, "-filters"], capture_output=True, text=True, timeout=4)
            if "ddagrab" in r.stdout or "ddagrab" in r.stderr:
                return exe
        except Exception:
            continue

    # Fallback to standard which if nothing else
    shutil_which = shutil.which("ffmpeg")
    return shutil_which


def detect_gpu_hardware() -> Tuple[str, str, str]:
    """
    Detects GPU and returns (recommended_encoder, gpu_name, description).
    Possible encoders: 'h264_nvenc', 'h264_amf', 'h264_qsv', 'libx264'.
    """
    gpu_names = []
    try:
        import win32com.client
        wmi = win32com.client.GetObject("winmgmts:")
        controllers = wmi.InstancesOf("Win32_VideoController")
        for c in controllers:
            if c.Name:
                gpu_names.append(c.Name.strip())
    except Exception:
        pass

    full_name = " / ".join(gpu_names) if gpu_names else "Generic Video Adapter"
    upper = full_name.upper()

    if any(k in upper for k in ["NVIDIA", "GEFORCE", "RTX", "GTX", "QUADRO"]):
        return "h264_nvenc", full_name, "NVIDIA NVENC (Аппаратный сверхбыстрый энкодер)"
    elif any(k in upper for k in ["AMD", "RADEON", "ADVANCED MICRO DEVICES"]):
        return "h264_amf", full_name, "AMD AMF (Аппаратный энкодер Radeon)"
    elif any(k in upper for k in ["INTEL", "ARC", "IRIS", "UHD"]):
        return "h264_qsv", full_name, "Intel QuickSync (Аппаратный энкодер Intel)"
    else:
        return "libx264", full_name, "CPU Программный энкодер (x264 Ultrafast)"


def get_encoder_args(encoder: str) -> str:
    """Returns ultra-low latency command line arguments for the chosen encoder."""
    if encoder == "h264_nvenc":
        return "-c:v h264_nvenc -preset p1 -tune ull -zerolatency 1 -forced-idr 1 -repeat-headers 1 -bf 0"
    elif encoder == "h264_amf":
        return "-c:v h264_amf -usage ultralowlatency -quality speed -header_insertion_mode idr -bf 0"
    elif encoder == "h264_qsv":
        return "-c:v h264_qsv -preset veryfast -low_delay_brc 1 -forced-idr 1 -bf 0"
    else:
        return "-c:v libx264 -preset ultrafast -tune zerolatency -bf 0 -pix_fmt yuv420p"


def get_pixel_format(encoder: str) -> str:
    return "format=yuv420p" if encoder == "libx264" else "format=nv12"


def enumerate_displays() -> List[Dict]:
    """Enumerates all active desktop displays with resolution and refresh rate."""
    displays = []
    try:
        import win32api
        i = 0
        while True:
            try:
                dev = win32api.EnumDisplayDevices(None, i)
            except Exception:
                break
            if not dev:
                break
            if dev.StateFlags & 1:  # DISPLAY_DEVICE_ATTACHED_TO_DESKTOP
                try:
                    settings = win32api.EnumDisplaySettings(dev.DeviceName, -1)
                    is_primary = bool(dev.StateFlags & 4)
                    width = settings.PelsWidth
                    height = settings.PelsHeight
                    freq = settings.DisplayFrequency
                    name = dev.DeviceString or f"Дисплей #{i}"
                    
                    # Check if this is virtual display
                    is_virtual = False
                    if "Virtual" in name or "Idd" in name or (width == 1280 and height == 800 and not is_primary):
                        is_virtual = True

                    displays.append({
                        "idx": len(displays),
                        "device_idx": i,
                        "name": name,
                        "dev_name": dev.DeviceName,
                        "width": width,
                        "height": height,
                        "freq": freq,
                        "is_primary": is_primary,
                        "is_virtual": is_virtual,
                        "label": f"#{len(displays)}: {name} ({width}x{height} @ {freq}Hz)" + (" [Виртуальный Steam Deck]" if is_virtual else (" [Основной]" if is_primary else ""))
                    })
                except Exception:
                    pass
            i += 1
    except Exception as e:
        print(f"[DeckDisplay Engine] Note on display enumeration: {e}")

    if not displays:
        displays.append({
            "idx": 0,
            "device_idx": 0,
            "name": "Основной дисплей",
            "dev_name": "\\\\.\\DISPLAY1",
            "width": 1920,
            "height": 1080,
            "freq": 60,
            "is_primary": True,
            "is_virtual": False,
            "label": "#0: Основной дисплей (Автовыбор)"
        })
    return displays


class StreamManager:
    """Manages the FFmpeg / C++ server streaming process and real-time telemetry."""

    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self.is_streaming: bool = False
        self.start_time: float = 0.0
        self.monitor_thread: Optional[threading.Thread] = None
        self._stop_requested: bool = False

        # Callbacks
        self.on_metrics: Optional[Callable[[int, str, float, int, float], None]] = None
        self.on_status: Optional[Callable[[bool, str], None]] = None
        self.on_log: Optional[Callable[[str], None]] = None

    def start_stream(
        self,
        deck_ip: str,
        port: int,
        output_idx: int,
        framerate: int,
        encoder: str,
        bitrate: str
    ) -> Tuple[bool, str]:
        """Launches the video stream process."""
        if self.is_streaming:
            return True, "Трансляция уже запущена"

        ffmpeg_bin = find_ffmpeg_binary()
        if not ffmpeg_bin:
            return False, "FFmpeg не найден! Установите FFmpeg через кнопку в приложении или 'winget install Gyan.FFmpeg'."

        # Auto GPU encoder resolution
        actual_encoder = encoder
        if encoder == "auto":
            detected_enc, _, _ = detect_gpu_hardware()
            actual_encoder = detected_enc

        # Validate display output index against active displays
        active_displays = enumerate_displays()
        valid_indices = [d.get("idx", 0) for d in active_displays]
        if output_idx not in valid_indices:
            output_idx = 0

        enc_args = get_encoder_args(actual_encoder)
        pix_format = get_pixel_format(actual_encoder)

        # Build ddagrab command line
        ddagrab_filter = f"ddagrab=output_idx={output_idx}:framerate={framerate}:draw_mouse=1,hwdownload,format=bgra,{pix_format}"
        udp_url = f"udp://{deck_ip}:{port}?pkt_size=1400"

        cmd = [
            ffmpeg_bin,
            "-hide_banner",
            "-loglevel", "info",
            "-f", "lavfi",
            "-i", ddagrab_filter,
        ]
        cmd.extend(enc_args.split())
        cmd.extend([
            "-b:v", bitrate,
            "-maxrate", bitrate,
            "-bufsize", "500k",
            "-g", str(framerate),
            "-f", "h264",
            udp_url
        ])

        if self.on_log:
            self.on_log(f"[DeckDisplay] Запуск трансляции (Дисплей #{output_idx}, {framerate} FPS, кодер {actual_encoder})")
            self.on_log(f"[FFmpeg] Команда: {' '.join(cmd)}")

        self._stop_requested = False
        try:
            # Creation flags to prevent black console window
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            creationflags = 0x08000000  # CREATE_NO_WINDOW

            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                startupinfo=startupinfo,
                creationflags=creationflags
            )
        except Exception as e:
            return False, f"Ошибка запуска FFmpeg: {e}"

        self.is_streaming = True
        self.start_time = time.time()

        if self.on_status:
            self.on_status(True, f"Трансляция активна: {deck_ip}:{port} ({framerate} FPS, {actual_encoder})")

        self.monitor_thread = threading.Thread(target=self._read_telemetry, daemon=True)
        self.monitor_thread.start()

        return True, "Трансляция успешно запущена"

    def stop_stream(self) -> None:
        """Stops the streaming process cleanly."""
        self._stop_requested = True
        if self.process and self.is_streaming:
            if self.on_log:
                self.on_log("[DeckDisplay] Остановка трансляции...")

            try:
                # Send 'q' to ffmpeg stdin for graceful shutdown
                if self.process.stdin:
                    self.process.stdin.write("q\n")
                    self.process.stdin.flush()
                self.process.wait(timeout=1.5)
            except Exception:
                try:
                    self.process.terminate()
                    self.process.wait(timeout=1.0)
                except Exception:
                    try:
                        self.process.kill()
                    except Exception:
                        pass

        self.process = None
        self.is_streaming = False

        if self.on_status:
            self.on_status(False, "Трансляция остановлена")

    def _read_telemetry(self) -> None:
        """Reads stderr from FFmpeg and parses FPS, bitrate, speed, and frames."""
        fps_pattern = re.compile(r"fps=\s*([\d\.]+)")
        q_pattern = re.compile(r"q=\s*([\d\.-]+)")
        bitrate_pattern = re.compile(r"bitrate=\s*([\d\.]+\s*\w+/s)")
        speed_pattern = re.compile(r"speed=\s*([\d\.]+)x")
        frame_pattern = re.compile(r"frame=\s*(\d+)")

        last_fps = 0
        last_bitrate = "0 kbits/s"
        last_speed = 1.0
        last_frames = 0

        while self.is_streaming and self.process and self.process.stderr:
            line = self.process.stderr.readline()
            if not line:
                break

            line_str = line.strip()
            if not line_str:
                continue

            # Check for error diagnostics
            lower = line_str.lower()
            if "desktop duplication access denied" in lower:
                if self.on_log:
                    self.on_log("[FFmpeg Ошибка] Захват экрана отклонен (Desktop duplication access denied).")
                    self.on_log("[Диагностика] Причины: экран заблокирован, открыт защищенный UAC, либо стороннее ПО (AMD ReLive, NVIDIA ShadowPlay, OBS) блокирует DXGI захват.")
            elif any(k in lower for k in ["error", "warning", "denied", "failed", "invalid", "cannot"]):
                if self.on_log:
                    self.on_log(f"[FFmpeg] {line_str}")
            elif not line_str.startswith("frame=") and not line_str.startswith("fps="):
                # Log startup / stream info lines
                if self.on_log and any(k in lower for k in ["opening", "output", "stream", "encoder", "configuration"]):
                    self.on_log(f"[FFmpeg] {line_str}")

            m_fps = fps_pattern.search(line_str)
            if m_fps:
                try:
                    last_fps = int(float(m_fps.group(1)))
                except ValueError:
                    pass

            m_br = bitrate_pattern.search(line_str)
            if m_br:
                last_bitrate = m_br.group(1)

            m_spd = speed_pattern.search(line_str)
            if m_spd:
                try:
                    last_speed = float(m_spd.group(1))
                except ValueError:
                    pass

            m_fr = frame_pattern.search(line_str)
            if m_fr:
                try:
                    last_frames = int(m_fr.group(1))
                except ValueError:
                    pass

            uptime = time.time() - self.start_time
            if self.on_metrics:
                self.on_metrics(last_fps, last_bitrate, last_speed, last_frames, uptime)

        # Process exited
        if not self._stop_requested and self.is_streaming:
            self.is_streaming = False
            exit_code = self.process.poll() if self.process else None
            msg = f"Процесс трансляции завершился (код: {exit_code})"
            if self.on_log:
                self.on_log(f"[DeckDisplay] {msg}")
            if self.on_status:
                self.on_status(False, msg)
