# ==============================================================================
# DeckDisplay - Windows Executable Packager
# Builds a standalone DeckDisplay.exe using PyInstaller.
# ==============================================================================

import os
import shutil
import subprocess
import sys


def build():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    print("=== DeckDisplay Executable Builder ===")
    print(f"Working directory: {script_dir}")

    # 1. Ensure icons exist
    ico_path = os.path.join(script_dir, "icon.ico")
    png_path = os.path.join(script_dir, "icon.png")
    if not os.path.exists(ico_path) or not os.path.exists(png_path):
        print("Generating application icons...")
        import create_icon
        create_icon.create_deckdisplay_icon()

    main_script = os.path.join(script_dir, "deckdisplay_app.py")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconsole",
        "--onefile",
        "--name", "DeckDisplay",
        "--icon", ico_path,
        "--add-data", f"{ico_path};.",
        "--add-data", f"{png_path};.",
        "--collect-all", "customtkinter",
        "--collect-all", "pystray",
        "--collect-all", "PIL",
        "--hidden-import", "win32api",
        "--hidden-import", "win32con",
        "--hidden-import", "win32gui",
        "--hidden-import", "win32process",
        "--hidden-import", "win32com.client",
        "--hidden-import", "screeninfo",
        "--hidden-import", "darkdetect",
        "--clean",
        "-y",
        main_script
    ]

    print("Running PyInstaller with arguments:")
    print(" ".join(cmd))

    res = subprocess.run(cmd)
    if res.returncode != 0:
        print(f"[FAIL] PyInstaller failed with exit code {res.returncode}")
        sys.exit(res.returncode)

    dist_exe = os.path.join(script_dir, "dist", "DeckDisplay.exe")
    if os.path.exists(dist_exe):
        size_mb = os.path.getsize(dist_exe) / (1024 * 1024)
        print(f"\n[SUCCESS] Ready-to-run executable created: {dist_exe} ({size_mb:.2f} MB)")
        
        # Deploy executable to windows-host/ and project root
        host_exe = os.path.join(script_dir, "DeckDisplay.exe")
        root_exe = os.path.abspath(os.path.join(script_dir, "..", "DeckDisplay.exe"))
        try:
            shutil.copy2(dist_exe, host_exe)
            print(f"[DEPLOY] Copied to: {host_exe}")
            shutil.copy2(dist_exe, root_exe)
            print(f"[DEPLOY] Copied to project root: {root_exe}")
        except Exception as e:
            print(f"[NOTE] Copy error: {e}")
    else:
        print("[FAIL] Output executable was not found in dist/")
        sys.exit(1)


if __name__ == "__main__":
    build()
