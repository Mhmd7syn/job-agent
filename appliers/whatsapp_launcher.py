import os
import sys
import time
import json
import logging
import urllib.parse
import subprocess
import threading
import tempfile
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from appliers.gmail_launcher import copy_file_to_clipboard, reveal_in_explorer
from appliers.whatsapp_copilot import normalize_phone_number, build_whatsapp_desktop_url, build_wa_me_url, build_whatsapp_web_url


def _inject_attachment_async(delay_seconds: float = 2.5):
    """
    Background worker that activates WhatsApp Desktop and simulates Ctrl+V
    to automatically attach the file from the Windows clipboard into the chat.
    This opens the native Document Attachment Preview in WhatsApp with the Send button.
    """
    time.sleep(delay_seconds)
    try:
        ps_code = r"""
try {
    $wshell = New-Object -ComObject WScript.Shell
    $activated = $wshell.AppActivate("WhatsApp")
    if (-not $activated) {
        # Retry once after 1 second
        Start-Sleep -Milliseconds 1000
        $activated = $wshell.AppActivate("WhatsApp")
    }
    if ($activated) {
        Start-Sleep -Milliseconds 400
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.SendKeys]::SendWait("^v")
        Write-Output "PASTE_SUCCESS"
    } else {
        Write-Output "ACTIVATE_FAILED"
    }
} catch {
    Write-Error $_.Exception.Message
    exit 1
}
"""
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".ps1", delete=False) as f:
            f.write(ps_code)
            ps_file = f.name

        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps_file]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

        try:
            os.remove(ps_file)
        except Exception:
            pass

        if "PASTE_SUCCESS" in res.stdout:
            logger.info("Successfully injected CV attachment via Ctrl+V into WhatsApp Desktop.")
        else:
            logger.debug(f"WhatsApp attachment injection status: {res.stdout.strip()}")
    except Exception as e:
        logger.warning(f"Error during async WhatsApp attachment injection: {e}")


def launch_whatsapp_desktop(
    phone: str,
    pitch: str,
    cv_path: Optional[str] = None,
    auto_attach: bool = True
) -> Dict[str, Any]:
    """
    Launches WhatsApp Desktop application with the target phone and pitch pre-filled:
    1. Copies the matched CV PDF to the Windows Clipboard (CF_HDROP).
    2. Opens WhatsApp Desktop via whatsapp:// protocol.
    3. Asynchronously triggers Ctrl+V so WhatsApp Desktop opens the Document Send Preview,
       waiting for the user to review and click the green Send button.
    """
    clean_phone = normalize_phone_number(phone)
    desktop_url = build_whatsapp_desktop_url(clean_phone, pitch)
    wa_me_url = build_wa_me_url(clean_phone, pitch)

    cv_copied = False
    if cv_path and os.path.exists(cv_path):
        cv_copied = copy_file_to_clipboard(cv_path)

    # Launch desktop application via Windows shell
    launched = False
    try:
        if sys.platform == "win32":
            # Using cmd start or os.startfile
            try:
                os.startfile(desktop_url)
                launched = True
            except Exception:
                subprocess.Popen(["cmd.exe", "/c", "start", "", desktop_url], shell=True)
                launched = True
        else:
            subprocess.Popen(["xdg-open", wa_me_url])
            launched = True
    except Exception as e:
        logger.error(f"Failed to launch WhatsApp Desktop: {e}")
        return {
            "status": "error",
            "message": f"Could not launch WhatsApp Desktop: {str(e)}",
            "desktop_url": desktop_url,
            "wa_me_url": wa_me_url
        }

    # If requested and CV was copied, launch background thread to simulate paste
    if auto_attach and cv_copied and sys.platform == "win32":
        t = threading.Thread(target=_inject_attachment_async, args=(2.5,), daemon=True)
        t.start()

    return {
        "status": "success",
        "launched_via": "whatsapp_desktop",
        "phone": clean_phone,
        "desktop_url": desktop_url,
        "wa_me_url": wa_me_url,
        "cv_copied_to_clipboard": cv_copied,
        "cv_filename": os.path.basename(cv_path) if cv_path else None,
        "cv_path": cv_path,
        "auto_attach_triggered": auto_attach and cv_copied
    }


def launch_whatsapp_web(
    phone: str,
    pitch: str,
    cv_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Launches WhatsApp in web browser as a secondary fallback.
    Copies CV PDF to clipboard so user can press Ctrl+V in the web chat.
    """
    clean_phone = normalize_phone_number(phone)
    wa_me_url = build_wa_me_url(clean_phone, pitch)

    cv_copied = False
    if cv_path and os.path.exists(cv_path):
        cv_copied = copy_file_to_clipboard(cv_path)

    try:
        import webbrowser
        webbrowser.open(wa_me_url)
        launched = True
    except Exception as e:
        logger.error(f"Failed to open WhatsApp web URL: {e}")
        launched = False

    return {
        "status": "success" if launched else "error",
        "launched_via": "web_browser",
        "phone": clean_phone,
        "wa_me_url": wa_me_url,
        "cv_copied_to_clipboard": cv_copied,
        "cv_filename": os.path.basename(cv_path) if cv_path else None,
        "cv_path": cv_path
    }
