import os
import subprocess
import sys
import time
import urllib.request
import webbrowser

APP_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(APP_DIR)

PYTHON_EXE = os.path.join(APP_DIR, "venv", "Scripts", "python.exe")
URL = "http://localhost:8000"

def is_server_running():
    try:
        req = urllib.request.Request(URL, headers={"User-Agent": "Launcher"})
        with urllib.request.urlopen(req, timeout=1) as resp:
            return resp.status in (200, 301, 302, 307, 404)
    except Exception:
        return False

def start_server():
    if is_server_running():
        return

    CREATE_NO_WINDOW = 0x08000000
    subprocess.Popen(
        [PYTHON_EXE, "-m", "backend.main"],
        cwd=APP_DIR,
        creationflags=CREATE_NO_WINDOW,
        close_fds=True
    )

    for _ in range(50):
        time.sleep(0.3)
        if is_server_running():
            break

if __name__ == "__main__":
    start_server()
    webbrowser.open(URL)
