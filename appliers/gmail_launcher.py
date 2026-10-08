import os
import sys
import urllib.parse
import webbrowser
import subprocess
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

def build_gmail_compose_url(recipient: str, subject: str, body: str) -> str:
    """
    Constructs a Gmail Web / PWA compose link with pre-filled fields.
    """
    params = {
        "view": "cm",
        "fs": "1",
        "to": recipient or "",
        "su": subject or "",
        "body": body or ""
    }
    encoded = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    return f"https://mail.google.com/mail/?{encoded}"

def copy_file_to_clipboard(file_path: str) -> bool:
    """
    Copies a file to the Windows Clipboard using CF_HDROP format.
    Allows user to immediately press Ctrl + V inside Gmail compose to attach the file.
    """
    if not file_path or not os.path.exists(file_path):
        return False

    abs_path = os.path.abspath(file_path)
    if sys.platform != "win32":
        return False

    try:
        import ctypes
        from ctypes import wintypes

        GMEM_MOVEABLE = 0x0002
        CF_HDROP = 15

        class DROPFILES(ctypes.Structure):
            _fields_ = [
                ("pFiles", wintypes.DWORD),
                ("pt", wintypes.POINT),
                ("fNC", wintypes.BOOL),
                ("fWide", wintypes.BOOL),
            ]

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        user32.SetClipboardData.restype = wintypes.HANDLE

        file_bytes = (abs_path + '\0\0').encode('utf-16-le')
        dropfiles = DROPFILES()
        dropfiles.pFiles = ctypes.sizeof(DROPFILES)
        dropfiles.pt = wintypes.POINT(0, 0)
        dropfiles.fNC = False
        dropfiles.fWide = True

        total_size = ctypes.sizeof(DROPFILES) + len(file_bytes)
        h_global = kernel32.GlobalAlloc(GMEM_MOVEABLE, total_size)
        if not h_global:
            return False

        p_global = kernel32.GlobalLock(h_global)
        if not p_global:
            kernel32.GlobalFree(h_global)
            return False

        ctypes.memmove(p_global, ctypes.byref(dropfiles), ctypes.sizeof(DROPFILES))
        ctypes.memmove(p_global + ctypes.sizeof(DROPFILES), file_bytes, len(file_bytes))
        kernel32.GlobalUnlock(h_global)

        if not user32.OpenClipboard(None):
            kernel32.GlobalFree(h_global)
            return False

        user32.EmptyClipboard()
        user32.SetClipboardData(CF_HDROP, h_global)
        user32.CloseClipboard()
        return True
    except Exception as e:
        logger.warning(f"Error copying file to clipboard: {e}")
        return False

def reveal_in_explorer(file_path: str) -> bool:
    """
    Reveals the file in Windows File Explorer with the file selected.
    """
    if not file_path or not os.path.exists(file_path):
        return False
    if sys.platform != "win32":
        return False
    try:
        norm_path = os.path.normpath(os.path.abspath(file_path))
        subprocess.Popen(f'explorer.exe /select,"{norm_path}"')
        return True
    except Exception as e:
        logger.warning(f"Error revealing in explorer: {e}")
        return False

def prepare_gmail_launch(
    recipient: str,
    subject: str,
    body: str,
    cv_path: Optional[str] = None,
    open_browser: bool = False
) -> Dict[str, Any]:
    """
    Prepares Gmail compose URL, copies CV to clipboard for Ctrl+V attachment,
    and optionally launches the browser.
    """
    url = build_gmail_compose_url(recipient, subject, body)
    clipboard_ok = False
    if cv_path and os.path.exists(cv_path):
        clipboard_ok = copy_file_to_clipboard(cv_path)

    if open_browser:
        try:
            webbrowser.open(url)
        except Exception as e:
            logger.warning(f"Failed to open browser: {e}")

    return {
        "status": "success",
        "gmail_url": url,
        "recipient": recipient,
        "subject": subject,
        "cv_path": cv_path,
        "cv_in_clipboard": clipboard_ok,
        "instructions": "Gmail opened with pre-filled draft. Press Ctrl + V inside Gmail to attach your tailored CV."
    }
