import webview
import subprocess
import logging
import time
import sys
import os
import socket
import shutil

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def resolve_ngrok_bin():
    """Finds ngrok binary across PATH, WindowsApps, and local automation folder."""
    bin_path = shutil.which("ngrok")
    if bin_path and os.path.exists(bin_path):
        return bin_path
    win_apps = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WindowsApps", "ngrok.exe")
    if os.path.exists(win_apps):
        return win_apps
    auto_bin = r"C:\automation\ngrok\ngrok.exe"
    if os.path.exists(auto_bin):
        return auto_bin
    return None

def is_port_open(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.25)
        return s.connect_ex(("127.0.0.1", port)) == 0

def start_desktop_app():
    # Start the FastAPI server as a subprocess without a console window
    # creationflags=0x08000000 is CREATE_NO_WINDOW in Windows
    python_exe = sys.executable.replace("pythonw.exe", "python.exe").replace("job-agent-w.exe", "job-agent.exe")
    log_path = os.path.join(BASE_DIR, "uvicorn_server.log")
    log_file = open(log_path, "a", encoding="utf-8")
    server_process = subprocess.Popen(
        [python_exe, "-m", "uvicorn", "web.app:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=BASE_DIR,
        stdout=log_file,
        stderr=log_file,
        creationflags=0x08000000
    )

    # Start ngrok tunnel if configured and not already running
    ngrok_process = None
    ngrok_bin = resolve_ngrok_bin()
    try:
        from core import config as app_config
        ngrok_domain = getattr(app_config, "NGROK_DOMAIN", "") or os.getenv("NGROK_DOMAIN", "")
    except Exception:
        ngrok_domain = os.getenv("NGROK_DOMAIN", "")

    if ngrok_bin and ngrok_domain and not is_port_open(4040):
        try:
            ngrok_process = subprocess.Popen(
                [ngrok_bin, "http", "8000", f"--url={ngrok_domain}"],
                cwd=BASE_DIR,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=0x08000000
            )
        except Exception as e:
            logging.warning(f"Failed to launch ngrok tunnel: {e}")

    # Wait until the FastAPI server is actively listening before launching WebView (prevents ERR_CONNECTION_REFUSED)
    for _ in range(40):
        try:
            with socket.create_connection(("127.0.0.1", 8000), timeout=0.25):
                break
        except (ConnectionRefusedError, OSError):
            if server_process.poll() is not None:
                break
            time.sleep(0.25)

    # Create the native desktop window pointing to the server
    try:
        webview.create_window('Job Agent', 'http://127.0.0.1:8000', width=1200, height=800)

        # Start the UI loop with the logo icon
        icon_path = os.path.join(BASE_DIR, 'logo.ico')
        webview.start(icon=icon_path)
    finally:
        # When the user closes the window, or if an error occurs, terminate both server and ngrok
        if server_process:
            server_process.terminate()
            try:
                server_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                server_process.kill()
        log_file.close()

        if ngrok_process:
            ngrok_process.terminate()
            try:
                ngrok_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                ngrok_process.kill()

if __name__ == '__main__':
    start_desktop_app()
