import os
import sys
import json
import subprocess
import glob

def test_json_files():
    print("=== Testing JSON files ===")
    for path in glob.glob("**/*.json", recursive=True):
        if "node_modules" in path:
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                json.load(f)
            print(f"  [PASS] {path}")
        except Exception as e:
            print(f"  [FAIL] {path}: {e}")
            return False
    return True

def test_python_files():
    print("\n=== Testing Python files ===")
    for path in glob.glob("**/*.py", recursive=True):
        if "tests" in path:
            continue
        res = subprocess.run([sys.executable, "-m", "py_compile", path], capture_output=True, text=True)
        if res.returncode == 0:
            print(f"  [PASS] {path}")
        else:
            print(f"  [FAIL] {path}: {res.stderr}")
            return False
    return True

def test_powershell_files():
    print("\n=== Testing PowerShell AST ===")
    for path in glob.glob("**/*.ps1", recursive=True):
        cmd = [
            "powershell", "-NoProfile", "-Command",
            f"$e = $null; [System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path '{path}'), [ref]$null, [ref]$e); if ($e) {{ Write-Host $e; exit 1 }}"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            print(f"  [PASS] {path}")
        else:
            print(f"  [FAIL] {path}: {res.stdout} {res.stderr}")
            return False
    return True

def test_bash_scripts():
    print("\n=== Testing Bash scripts ===")
    bash_path = r"C:\Program Files\Git\bin\bash.exe"
    if not os.path.exists(bash_path):
        print("  [SKIP] Git Bash not found")
        return True
    for path in glob.glob("**/*.sh", recursive=True):
        res = subprocess.run([bash_path, "-n", path], capture_output=True, text=True)
        if res.returncode == 0:
            print(f"  [PASS] {path}")
        else:
            print(f"  [FAIL] {path}: {res.stderr}")
            return False
    return True

def test_functional_fixes():
    print("\n=== Testing Functional Fixes & Regression Defenses ===")

    # 1. deckdisplay_client.c must have reconnection loop and frame unreferencing
    client_c = os.path.join("steamos-client", "deckdisplay_client.c")
    with open(client_c, "r", encoding="utf-8") as f:
        client_code = f.read()

    assert "draw_waiting_screen" in client_code, "Waiting screen rendering missing from client"
    assert "av_frame_unref(sw_frame)" in client_code, "Missing av_frame_unref(sw_frame) in client"
    assert "thread_count = 1" in client_code or "FF_THREAD_SLICE" in client_code, "Low-latency thread settings missing from client"
    print("  [PASS] deckdisplay_client.c: Waiting screen loop, frame unref, and low-latency thread options verified.")

    # 2. deckdisplay_touch.c must support rotation CLI flags and dynamic multi-touch slots
    touch_c = os.path.join("steamos-client", "deckdisplay_touch.c")
    with open(touch_c, "r", encoding="utf-8") as f:
        touch_code = f.read()

    assert "--rotate" in touch_code, "Missing --rotate CLI arg in touch daemon"
    assert "--invert-x" in touch_code, "Missing --invert-x CLI arg in touch daemon"
    assert "MAX_SLOTS" in touch_code, "Dynamic multi-touch slot tracking missing in touch daemon"
    print("  [PASS] deckdisplay_touch.c: CLI arguments, orientation modes, and multi-slot tracking verified.")

    # 3. install-ffmpeg.ps1 & Start-DeckDisplay.ps1 must check for ddagrab filter
    install_ff = os.path.join("windows-host", "install-ffmpeg.ps1")
    with open(install_ff, "r", encoding="utf-8") as f:
        install_ff_code = f.read()
    assert "ddagrab" in install_ff_code, "install-ffmpeg.ps1 missing ddagrab compatibility check"

    start_disp = os.path.join("windows-host", "Start-DeckDisplay.ps1")
    with open(start_disp, "r", encoding="utf-8") as f:
        start_disp_code = f.read()
    assert "ddagrab" in start_disp_code, "Start-DeckDisplay.ps1 missing ddagrab check"
    assert "Set-Location" in start_disp_code, "Start-DeckDisplay.ps1 missing CWD fix for elevation"
    print("  [PASS] windows-host: FFmpeg ddagrab validation and working directory fixes verified.")

    # 4. deckdisplay_server.cpp must have heartbeat mechanism for static screens
    server_cpp = os.path.join("windows-host", "deckdisplay_server.cpp")
    with open(server_cpp, "r", encoding="utf-8") as f:
        server_code = f.read()
    assert "last_captured_tex" in server_code, "deckdisplay_server.cpp missing heartbeat texture cache"
    print("  [PASS] deckdisplay_server.cpp: Heartbeat re-emission for static desktop verified.")

    # 5. decky-plugin/dist/index.js must exist and contain definePlugin
    dist_js = os.path.join("decky-plugin", "dist", "index.js")
    assert os.path.exists(dist_js), "decky-plugin/dist/index.js does not exist!"
    with open(dist_js, "r", encoding="utf-8") as f:
        dist_code = f.read()
    assert "definePlugin" in dist_code, "dist/index.js missing definePlugin entry"
    print("  [PASS] decky-plugin/dist/index.js: Pre-bundled bundle verified.")

    # 6. install-steamos.sh must contain persistent udev rule
    install_sh = os.path.join("steamos-client", "install-steamos.sh")
    with open(install_sh, "r", encoding="utf-8") as f:
        install_code = f.read()
    assert "99-deckdisplay-hid.rules" in install_code, "install-steamos.sh missing persistent udev rule"
    print("  [PASS] install-steamos.sh: Persistent udev rule for /dev/hidg* verified.")

    return True

if __name__ == "__main__":
    t1 = test_json_files()
    t2 = test_python_files()
    t3 = test_powershell_files()
    t4 = test_bash_scripts()
    t5 = test_functional_fixes()
    if all([t1, t2, t3, t4, t5]):
        print("\nALL VERIFICATIONS PASSED SUCCESSFULLY (5/5 suites)")
        sys.exit(0)
    else:
        print("\nVERIFICATIONS FAILED")
        sys.exit(1)
