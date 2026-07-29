import webview
import subprocess
import time
import sys
import os
import socket

def start_desktop_app():
    # Start the FastAPI server as a subprocess without a console window
    # creationflags=0x08000000 is CREATE_NO_WINDOW in Windows
    python_exe = sys.executable.replace("pythonw.exe", "python.exe")
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uvicorn_server.log")
    log_file = open(log_path, "a", encoding="utf-8")
    server_process = subprocess.Popen(
        [python_exe, "-m", "uvicorn", "web.app:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=os.path.dirname(os.path.abspath(__file__)),
        stdout=log_file,
        stderr=log_file,
        creationflags=0x08000000
    )

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
    
    # Process any pending alerts deferred from background scraping runs
    try:
        from core.config_tuner import process_pending_alerts
        process_pending_alerts()
    except Exception as e:
        print(f"Error processing pending alerts: {e}")

    webview.create_window('Job Agent', 'http://127.0.0.1:8000', width=1200, height=800)

    # Start the UI loop with the logo icon
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logo.ico')
    webview.start(icon=icon_path)

    # When the user closes the window, this unblocks and we terminate the server
    server_process.terminate()
    try:
        server_process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        server_process.kill()

if __name__ == '__main__':
    start_desktop_app()
