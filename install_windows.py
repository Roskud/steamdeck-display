import os
import sys
import subprocess

def install():
    print("Installing DeckDisplay dependencies for Windows...")
    
    # Check if FFmpeg installer exists
    ffmpeg_script = "windows-host/install-ffmpeg.ps1"
    if os.path.exists(ffmpeg_script):
        print("Installing FFmpeg via powershell...")
        try:
            # Need to run with Administrator privileges
            subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-File", ffmpeg_script], check=True)
            print("FFmpeg installation finished.")
        except subprocess.CalledProcessError as e:
            print(f"Error installing FFmpeg: {e}")
    else:
        print(f"FFmpeg installer not found: {ffmpeg_script}")
    
    print("Installation complete.")

if __name__ == "__main__":
    install()
