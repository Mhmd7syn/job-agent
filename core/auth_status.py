import os
import shutil
import sqlite3
import tempfile
import time
from typing import Dict, Any

from core.config import get_browser_user_data_dir


def check_platform_auth_status(user_data_dir: str | None = None) -> Dict[str, Dict[str, Any]]:
    """
    Inspects persistent browser profile cookies and storage to determine authentication status
    for supported job platforms (LinkedIn, Tanqeeb, Glassdoor, Bayt, Wuzzuf, Indeed, WhatsApp Web).
    Executes in milliseconds without launching or blocking the browser.
    """
    if not user_data_dir:
        user_data_dir = get_browser_user_data_dir()

    platforms = {
        "linkedin": {
            "name": "LinkedIn",
            "logged_in": False,
            "status": "Not Logged In",
            "icon": "fa-brands fa-linkedin",
            "color": "#0A66C2",
        },
        "tanqeeb": {
            "name": "Tanqeeb",
            "logged_in": False,
            "status": "Not Logged In",
            "icon": "fa-solid fa-magnifying-glass",
            "color": "#2563EB",
        },
        "glassdoor": {
            "name": "Glassdoor",
            "logged_in": False,
            "status": "Not Logged In",
            "icon": "fa-solid fa-building",
            "color": "#0CAA41",
        },
        "bayt": {
            "name": "Bayt",
            "logged_in": False,
            "status": "Not Logged In",
            "icon": "fa-solid fa-globe",
            "color": "#1E40AF",
        },
        "wuzzuf": {
            "name": "Wuzzuf",
            "logged_in": False,
            "status": "Not Logged In",
            "icon": "fa-solid fa-bullseye",
            "color": "#0055FF",
        },
        "indeed": {
            "name": "Indeed",
            "logged_in": False,
            "status": "Not Logged In",
            "icon": "fa-solid fa-file-lines",
            "color": "#2164F4",
        },
        "whatsapp": {
            "name": "WhatsApp Web",
            "logged_in": False,
            "status": "Not Paired",
            "icon": "fa-brands fa-whatsapp",
            "color": "#25D366",
        },
    }

    if not user_data_dir or not os.path.exists(user_data_dir):
        return platforms

    # 1. Check WhatsApp Web session via IndexedDB / LocalStorage in profile
    wa_idb = os.path.join(
        user_data_dir, "Default", "IndexedDB", "https_web.whatsapp.com_0.indexeddb.leveldb"
    )
    if os.path.exists(wa_idb):
        try:
            files = os.listdir(wa_idb)
            if any(f.endswith(".ldb") or f.endswith(".log") for f in files):
                platforms["whatsapp"]["logged_in"] = True
                platforms["whatsapp"]["status"] = "Session Paired"
        except Exception:
            pass

    # 2. Check Cookie Database
    cookies_path = os.path.join(user_data_dir, "Default", "Network", "Cookies")
    if not os.path.exists(cookies_path):
        # Check fallback legacy path
        cookies_path = os.path.join(user_data_dir, "Default", "Cookies")

    if not os.path.exists(cookies_path) or os.path.getsize(cookies_path) == 0:
        return platforms

    tmp_db = None
    try:
        tmp_fd, tmp_db = tempfile.mkstemp(suffix=".sqlite")
        os.close(tmp_fd)
        shutil.copy2(cookies_path, tmp_db)

        con = sqlite3.connect(tmp_db, timeout=2.0)
        cur = con.cursor()
        cur.execute("SELECT host_key, name, expires_utc FROM cookies")
        rows = cur.fetchall()
        con.close()

        now = time.time()

        for host, name, expires_utc in rows:
            host = host.lower()
            name = name.strip()

            # Check expiry: Windows epoch microseconds (1601) to Unix epoch (1970)
            unix_exp = (expires_utc / 1_000_000) - 11644473600 if expires_utc > 0 else 0
            is_valid = expires_utc == 0 or unix_exp > now

            if not is_valid:
                continue

            # LinkedIn
            if "linkedin.com" in host:
                if name == "li_at":
                    platforms["linkedin"]["logged_in"] = True
                    platforms["linkedin"]["status"] = "Active Session"

            # Tanqeeb
            elif "tanqeeb.com" in host:
                if name in ("token", "user_id", "in_tkr"):
                    platforms["tanqeeb"]["logged_in"] = True
                    platforms["tanqeeb"]["status"] = "Active Session"

            # Glassdoor
            elif "glassdoor.com" in host:
                if name in ("gdId", "asst", "at", "rl_user_id", "gd_door_onboarded"):
                    platforms["glassdoor"]["logged_in"] = True
                    platforms["glassdoor"]["status"] = "Active Session"

            # Indeed
            elif "indeed.com" in host:
                if (
                    name.startswith("__Secure-PassportAuthProxy")
                    or name in ("rememberMe", "SURF", "SOCK")
                ):
                    platforms["indeed"]["logged_in"] = True
                    platforms["indeed"]["status"] = "Active Session"

            # Bayt
            elif "bayt.com" in host:
                if name in ("UADCN", "brID", "nav-status"):
                    platforms["bayt"]["logged_in"] = True
                    platforms["bayt"]["status"] = "Active Session"

            # Wuzzuf
            elif "wuzzuf.net" in host:
                if name in ("wz_user", "wz_token", "session", "user_auth"):
                    platforms["wuzzuf"]["logged_in"] = True
                    platforms["wuzzuf"]["status"] = "Active Session"

    except Exception:
        # Fall back to currently evaluated platform dict on read failure
        pass
    finally:
        if tmp_db and os.path.exists(tmp_db):
            try:
                os.remove(tmp_db)
            except Exception:
                pass

    return platforms
