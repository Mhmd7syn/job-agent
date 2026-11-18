import json
import os
import shutil
import sqlite3
import tempfile
import time
from typing import Dict, Any

from core.config import get_browser_user_data_dir


def sync_profile_storage(user_data_dir: str):
    """
    Bidirectionally syncs cookies and storage between Edge's native profile root
    (e.g., .../job_agent/Network/Cookies) and Playwright's persistent context
    subfolder (e.g., .../job_agent/Default/Network/Cookies).
    """
    if not user_data_dir or not os.path.exists(user_data_dir):
        return

    # 1. Sync WhatsApp IndexedDB
    root_idb = os.path.join(user_data_dir, "IndexedDB", "https_web.whatsapp.com_0.indexeddb.leveldb")
    default_idb = os.path.join(user_data_dir, "Default", "IndexedDB", "https_web.whatsapp.com_0.indexeddb.leveldb")

    if os.path.exists(root_idb) and not os.path.exists(default_idb):
        try:
            os.makedirs(os.path.dirname(default_idb), exist_ok=True)
            shutil.copytree(root_idb, default_idb)
        except Exception:
            pass
    elif os.path.exists(default_idb) and not os.path.exists(root_idb):
        try:
            os.makedirs(os.path.dirname(root_idb), exist_ok=True)
            shutil.copytree(default_idb, root_idb)
        except Exception:
            pass

    # 2. Sync Cookies
    root_cookies = os.path.join(user_data_dir, "Network", "Cookies")
    default_cookies = os.path.join(user_data_dir, "Default", "Network", "Cookies")

    if os.path.exists(root_cookies) and os.path.exists(default_cookies):
        try:
            root_size = os.path.getsize(root_cookies)
            default_size = os.path.getsize(default_cookies)
            if root_size > default_size and root_size > 30000:
                shutil.copy2(root_cookies, default_cookies)
            elif default_size > root_size and default_size > 30000:
                shutil.copy2(default_cookies, root_cookies)
        except Exception:
            pass
    elif os.path.exists(root_cookies) and not os.path.exists(default_cookies):
        try:
            os.makedirs(os.path.dirname(default_cookies), exist_ok=True)
            shutil.copy2(root_cookies, default_cookies)
        except Exception:
            pass
    elif os.path.exists(default_cookies) and not os.path.exists(root_cookies):
        try:
            os.makedirs(os.path.dirname(root_cookies), exist_ok=True)
            shutil.copy2(default_cookies, root_cookies)
        except Exception:
            pass

    # 3. Ensure profile is branded as Job_agent
    brand_job_agent_profile(user_data_dir)


def brand_job_agent_profile(user_data_dir: str):
    """
    Ensures the profile metadata inside job_agent is clearly branded as 'Job_agent'
    and decoupled from Windows single-sign-on personal accounts.
    """
    if not user_data_dir or not os.path.exists(user_data_dir):
        return

    # Update Local State
    ls_path = os.path.join(user_data_dir, "Local State")
    if os.path.exists(ls_path):
        try:
            with open(ls_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            info_cache = data.setdefault("profile", {}).setdefault("info_cache", {})
            for p_key in ("Default", "job_agent"):
                if p_key in info_cache:
                    info_cache[p_key]["name"] = "Job_agent"
                    info_cache[p_key]["shortcut_name"] = "Job_agent"
                    info_cache[p_key]["user_name"] = ""
                    info_cache[p_key]["gaia_name"] = "Job_agent"
                    info_cache[p_key]["edge_account_first_name"] = "Job"
                    info_cache[p_key]["edge_account_last_name"] = "agent"
                    info_cache[p_key]["is_using_default_name"] = False
            with open(ls_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    # Update Preferences
    pref_path = os.path.join(user_data_dir, "Default", "Preferences")
    if os.path.exists(pref_path):
        try:
            with open(pref_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("profile", {})["name"] = "Job_agent"
            with open(pref_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass


def clone_profile_for_fallback(src_dir: str, dst_dir: str):
    """
    Clones essential cookies, IndexedDB, and branding from the persistent profile into
    a temporary fallback directory when a process lock prevents direct binding.
    """
    if not src_dir or not os.path.exists(src_dir) or not dst_dir:
        return

    # 1. Copy Cookies
    cookie_sources = [
        os.path.join(src_dir, "Default", "Network", "Cookies"),
        os.path.join(src_dir, "Network", "Cookies"),
    ]
    for cs in cookie_sources:
        if os.path.exists(cs) and os.path.getsize(cs) > 0:
            target = os.path.join(dst_dir, "Default", "Network", "Cookies")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            try:
                shutil.copy2(cs, target)
                break
            except Exception:
                pass

    # 2. Copy WhatsApp IndexedDB
    idb_sources = [
        os.path.join(src_dir, "Default", "IndexedDB", "https_web.whatsapp.com_0.indexeddb.leveldb"),
        os.path.join(src_dir, "IndexedDB", "https_web.whatsapp.com_0.indexeddb.leveldb"),
    ]
    for ids in idb_sources:
        if os.path.exists(ids):
            target = os.path.join(dst_dir, "Default", "IndexedDB", "https_web.whatsapp.com_0.indexeddb.leveldb")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            try:
                shutil.copytree(ids, target, dirs_exist_ok=True)
                break
            except Exception:
                pass

    # 3. Brand profile
    brand_job_agent_profile(dst_dir)


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

    # Sync storage between native Edge profile root and Playwright subfolder
    sync_profile_storage(user_data_dir)

    # 1. Check WhatsApp Web session via IndexedDB / LocalStorage in profile
    wa_candidates = [
        os.path.join(user_data_dir, "Default", "IndexedDB", "https_web.whatsapp.com_0.indexeddb.leveldb"),
        os.path.join(user_data_dir, "IndexedDB", "https_web.whatsapp.com_0.indexeddb.leveldb"),
    ]
    for wa_idb in wa_candidates:
        if os.path.exists(wa_idb):
            try:
                files = os.listdir(wa_idb)
                if any(f.endswith(".ldb") or f.endswith(".log") for f in files):
                    platforms["whatsapp"]["logged_in"] = True
                    platforms["whatsapp"]["status"] = "Session Paired"
                    break
            except Exception:
                pass

    # 2. Check Cookie Database across standard and profile-root paths
    cookie_candidates = [
        os.path.join(user_data_dir, "Network", "Cookies"),
        os.path.join(user_data_dir, "Default", "Network", "Cookies"),
        os.path.join(user_data_dir, "Cookies"),
        os.path.join(user_data_dir, "Default", "Cookies"),
    ]

    # Also check Edge's default profile as fallback candidate if running inside an Edge profile folder
    parent_dir = os.path.dirname(user_data_dir)
    default_profile_cookies = os.path.join(parent_dir, "Default", "Network", "Cookies")
    if os.path.exists(default_profile_cookies) and default_profile_cookies not in cookie_candidates:
        cookie_candidates.append(default_profile_cookies)

    now = time.time()

    for cand in cookie_candidates:
        if not os.path.exists(cand) or os.path.getsize(cand) == 0:
            continue

        if all(p["logged_in"] for k, p in platforms.items() if k != "whatsapp"):
            break

        tmp_db = None
        try:
            tmp_fd, tmp_db = tempfile.mkstemp(suffix=".sqlite")
            os.close(tmp_fd)
            shutil.copy2(cand, tmp_db)

            con = sqlite3.connect(tmp_db, timeout=2.0)
            cur = con.cursor()
            cur.execute("SELECT host_key, name, expires_utc FROM cookies")
            rows = cur.fetchall()
            con.close()

            for host, name, expires_utc in rows:
                host = host.lower()
                name = name.strip()

                unix_exp = (expires_utc / 1_000_000) - 11644473600 if expires_utc > 0 else 0
                is_valid = expires_utc == 0 or unix_exp > now

                if not is_valid:
                    continue

                # LinkedIn
                if "linkedin.com" in host and name == "li_at":
                    platforms["linkedin"]["logged_in"] = True
                    platforms["linkedin"]["status"] = "Active Session"

                # Tanqeeb
                elif "tanqeeb.com" in host and name in ("token", "user_id", "in_tkr"):
                    platforms["tanqeeb"]["logged_in"] = True
                    platforms["tanqeeb"]["status"] = "Active Session"

                # Glassdoor
                elif "glassdoor.com" in host and name in ("gdId", "asst", "at", "rl_user_id", "gd_door_onboarded"):
                    platforms["glassdoor"]["logged_in"] = True
                    platforms["glassdoor"]["status"] = "Active Session"

                # Indeed
                elif "indeed.com" in host and (
                    name.startswith("__Secure-PassportAuthProxy")
                    or name in ("rememberMe", "SURF", "SOCK")
                ):
                    platforms["indeed"]["logged_in"] = True
                    platforms["indeed"]["status"] = "Active Session"

                # Bayt
                elif "bayt.com" in host and name in ("UADCN", "brID", "nav-status"):
                    platforms["bayt"]["logged_in"] = True
                    platforms["bayt"]["status"] = "Active Session"

                # Wuzzuf
                elif "wuzzuf.net" in host and name in (
                    "wz_user", "wz_token", "session", "user_auth",
                    "user_access_token", "ci_sessions", "LiToken"
                ):
                    platforms["wuzzuf"]["logged_in"] = True
                    platforms["wuzzuf"]["status"] = "Active Session"

        except Exception:
            pass
        finally:
            if tmp_db and os.path.exists(tmp_db):
                try:
                    os.remove(tmp_db)
                except Exception:
                    pass

    # 3. Cache and resilience: merge with recent cache if any platform couldn't be read (e.g. file lock)
    cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "state")
    cache_file = os.path.join(cache_dir, "platform_auth_cache.json")

    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cached = json.load(f)
            for k, p in platforms.items():
                if not p["logged_in"] and k in cached and cached[k].get("logged_in"):
                    platforms[k]["logged_in"] = True
                    platforms[k]["status"] = cached[k].get("status", "Active Session")
        except Exception:
            pass

    try:
        os.makedirs(cache_dir, exist_ok=True)
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(platforms, f)
    except Exception:
        pass

    return platforms
