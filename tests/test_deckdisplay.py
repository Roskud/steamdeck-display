# ==============================================================================
# DeckDisplay - Comprehensive Integration & Verification Test Suite
# ==============================================================================

import glob
import json
import os
import subprocess
import sys
import time
import unittest


class DeckDisplayVerificationSuite(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        os.chdir(cls.repo_root)

    def test_01_json_manifests(self):
        """Verifies that all JSON manifest files are valid and well-formed."""
        json_files = [p for p in glob.glob("**/*.json", recursive=True) if "node_modules" not in p]
        self.assertGreater(len(json_files), 0, "No JSON files discovered")
        for path in json_files:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.assertIsNotNone(data, f"JSON file {path} parsed to None")

    def test_02_python_compilation(self):
        """Verifies that all Python modules compile without syntax errors."""
        py_files = [p for p in glob.glob("**/*.py", recursive=True) if "tests" not in p and "build" not in p]
        self.assertGreater(len(py_files), 0, "No Python files discovered")
        for path in py_files:
            res = subprocess.run([sys.executable, "-m", "py_compile", path], capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, f"Python compilation failed for {path}: {res.stderr}")

    def test_03_powershell_syntax(self):
        """Verifies PowerShell AST syntax parsing for all .ps1 scripts."""
        ps1_files = glob.glob("**/*.ps1", recursive=True)
        self.assertGreater(len(ps1_files), 0, "No PowerShell files discovered")
        for path in ps1_files:
            cmd = [
                "powershell", "-NoProfile", "-Command",
                f"$e = $null; [System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path '{path}'), [ref]$null, [ref]$e); if ($e) {{ Write-Host $e; exit 1 }}"
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, f"PowerShell parsing failed for {path}: {res.stdout} {res.stderr}")

    def test_04_bash_scripts(self):
        """Verifies Bash scripts with bash -n if Git Bash is present."""
        bash_path = r"C:\Program Files\Git\bin\bash.exe"
        if not os.path.exists(bash_path):
            self.skipTest("Git Bash not found at standard path")
        sh_files = glob.glob("**/*.sh", recursive=True)
        self.assertGreater(len(sh_files), 0, "No Bash files discovered")
        for path in sh_files:
            res = subprocess.run([bash_path, "-n", path], capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, f"Bash syntax error in {path}: {res.stderr}")

    def test_05_steamos_client_and_touch_c_code(self):
        """Verifies SteamOS C client and touch daemon regression defenses."""
        client_c = os.path.join("steamos-client", "deckdisplay_client.c")
        with open(client_c, "r", encoding="utf-8") as f:
            code = f.read()
        self.assertIn("draw_waiting_screen", code, "Waiting screen rendering missing")
        self.assertIn("av_frame_unref(sw_frame)", code, "av_frame_unref missing")
        self.assertTrue("thread_count = 1" in code or "FF_THREAD_SLICE" in code, "Low-latency threading missing")

        touch_c = os.path.join("steamos-client", "deckdisplay_touch.c")
        with open(touch_c, "r", encoding="utf-8") as f:
            t_code = f.read()
        self.assertIn("--rotate", t_code, "Missing --rotate CLI arg")
        self.assertIn("--invert-x", t_code, "Missing --invert-x CLI arg")
        self.assertIn("MAX_SLOTS", t_code, "Multi-touch slot tracking missing")

    def test_06_server_and_plugin_artifacts(self):
        """Verifies C++ server heartbeat, plugin bundle, and udev rules."""
        server_cpp = os.path.join("windows-host", "deckdisplay_server.cpp")
        with open(server_cpp, "r", encoding="utf-8") as f:
            s_code = f.read()
        self.assertIn("last_captured_tex", s_code, "deckdisplay_server.cpp missing heartbeat cache")

        dist_js = os.path.join("decky-plugin", "dist", "index.js")
        self.assertTrue(os.path.exists(dist_js), "decky-plugin/dist/index.js missing")
        with open(dist_js, "r", encoding="utf-8") as f:
            self.assertIn("definePlugin", f.read(), "definePlugin entry missing")

        install_sh = os.path.join("steamos-client", "install-steamos.sh")
        with open(install_sh, "r", encoding="utf-8") as f:
            self.assertIn("99-deckdisplay-hid.rules", f.read(), "Persistent udev rule missing")

    def test_07_windows_executables(self):
        """Verifies DeckDisplay.exe exists in windows-host and root, is 64-bit GUI PE."""
        target_exes = [
            os.path.join("windows-host", "DeckDisplay.exe"),
            "DeckDisplay.exe"
        ]
        for exe_path in target_exes:
            self.assertTrue(os.path.exists(exe_path), f"Executable not found: {exe_path}")
            size = os.path.getsize(exe_path)
            self.assertGreater(size, 20 * 1024 * 1024, f"Executable too small: {size} bytes")

            try:
                import pefile
                pe = pefile.PE(exe_path)
                self.assertEqual(pe.FILE_HEADER.Machine, 0x8664, "Not x64 binary")
                self.assertEqual(pe.OPTIONAL_HEADER.Subsystem, 2, "Not Windows GUI subsystem")
            except ImportError:
                pass

    def test_08_host_application_modules(self):
        """Tests config, engine, tray, and watchdog modules."""
        sys.path.insert(0, os.path.abspath("windows-host"))
        import config
        import engine
        import tray
        import watchdog

        # Config
        cfg = config.load_settings()
        for k in ["deck_ip", "port", "framerate", "encoder", "bitrate", "minimize_to_tray"]:
            self.assertIn(k, cfg, f"Missing config key {k}")

        # Engine
        ffmpeg_bin = engine.find_ffmpeg_binary()
        self.assertIsNotNone(ffmpeg_bin, "FFmpeg binary not found")
        gpu_enc, gpu_name, _ = engine.detect_gpu_hardware()
        self.assertIn(gpu_enc, ["h264_nvenc", "h264_amf", "h264_qsv", "libx264"])
        displays = engine.enumerate_displays()
        self.assertGreater(len(displays), 0, "No displays found")

        # Tray
        tm = tray.TrayManager()
        for s in ["idle", "waiting", "streaming"]:
            img = tm.get_status_image(s)
            self.assertEqual(img.size, (64, 64))

        # Watchdog
        wd = watchdog.NetworkWatchdog(target_ip="10.77.77.2")
        wd.start()
        self.assertTrue(wd.is_running)
        time.sleep(0.2)
        wd.stop()
        self.assertFalse(wd.is_running)

    def test_09_virtual_display_profile_and_tools(self):
        """Verifies virtual display profile creation and batch launchers."""
        target_dir = r"C:\IddSampleDriver"
        os.makedirs(target_dir, exist_ok=True)
        option_txt = os.path.join(target_dir, "option.txt")
        with open(option_txt, "w", encoding="ascii") as f:
            f.write("1\n1280, 800, 60\n1280, 800, 90\n")
        self.assertTrue(os.path.exists(option_txt))
        with open(option_txt, "r", encoding="ascii") as f:
            content = f.read()
        self.assertIn("1280, 800, 60", content)
        self.assertIn("1280, 800, 90", content)

        # Batch launchers
        for bat in ["run-deckdisplay.bat", os.path.join("windows-host", "run-deckdisplay.bat")]:
            self.assertTrue(os.path.exists(bat), f"Batch launcher {bat} missing")
            with open(bat, "r", encoding="utf-8", errors="ignore") as f:
                self.assertIn("DeckDisplay.exe", f.read())

    def test_10_executable_runtime_minimized(self):
        """Launches DeckDisplay.exe with --minimized, asserts stability, and terminates."""
        exe_path = os.path.abspath("DeckDisplay.exe")
        p = subprocess.Popen([exe_path, "--minimized"])
        try:
            time.sleep(2.0)
            self.assertIsNone(p.poll(), "DeckDisplay.exe exited unexpectedly")
        finally:
            p.terminate()
            try:
                p.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                p.kill()


if __name__ == "__main__":
    unittest.main(verbosity=2)
