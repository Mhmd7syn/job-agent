import json
import os
import shutil
import sqlite3
import tempfile
import time
from typing import Dict, Any

from core.config import get_browser_user_data_dir


def _get_cookie_count(path: str) -> int:
    if not path or not os.path.exists(path) or os.path.getsize(path) == 0:
        return 0
    try:
        con = sqlite3.connect(path, timeout=1.0)
        cur = con.cursor()
        cur.execute("SELECT count(*) FROM cookies")
        cnt = cur.fetchone()[0]
        con.close()
        return cnt
    except Exception:
        return 0


def _get_dir_mtime(dir_path: str) -> float:
    if not os.path.exists(dir_path):
        return 0.0
    latest = os.path.getmtime(dir_path)
    try:
        for entry in os.scandir(dir_path):
            try:
                em = entry.stat().st_mtime
                if em > latest:
                    latest = em
            except Exception:
                pass
    except Exception:
        pass
    return latest


def sync_profile_storage(user_data_dir: str):
    """
    Bidirectionally syncs cookies and storage between Edge's native profile root
    (e.g., .../job_agent/Network/Cookies) and Playwright's persistent context
    subfolder (e.g., .../job_agent/Default/Network/Cookies), as well as IndexedDB
    and Local Storage for all supported job platforms.
    """
    if not user_data_dir or not os.path.exists(user_data_dir):
        return

    # 1. Sync Cookies
    root_cookies = os.path.join(user_data_dir, "Network", "Cookies")
    default_cookies = os.path.join(user_data_dir, "Default", "Network", "Cookies")

    if os.path.exists(root_cookies) and os.path.exists(default_cookies):
        root_cnt = _get_cookie_count(root_cookies)
        default_cnt = _get_cookie_count(default_cookies)
        root_mtime = os.path.getmtime(root_cookies)
        default_mtime = os.path.getmtime(default_cookies)

        if root_cnt > 0 and (default_cnt == 0 or root_mtime > default_mtime + 2 or root_cnt > default_cnt):
            try:
                os.makedirs(os.path.dirname(default_cookies), exist_ok=True)
                shutil.copy2(root_cookies, default_cookies)
                for ext in ("-journal", "-wal", "-shm"):
                    rj = root_cookies + ext
                    dj = default_cookies + ext
                    if os.path.exists(rj):
                        shutil.copy2(rj, dj)
            except Exception:
                pass
        elif default_cnt > 0 and (root_cnt == 0 or default_mtime > root_mtime + 2 or default_cnt > root_cnt):
            try:
                os.makedirs(os.path.dirname(root_cookies), exist_ok=True)
                shutil.copy2(default_cookies, root_cookies)
                for ext in ("-journal", "-wal", "-shm"):
                    rj = root_cookies + ext
                    dj = default_cookies + ext
                    if os.path.exists(dj):
                        shutil.copy2(dj, rj)
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

    # 2. Sync IndexedDB across all supported platforms
    root_idb_dir = os.path.join(user_data_dir, "IndexedDB")
    default_idb_dir = os.path.join(user_data_dir, "Default", "IndexedDB")

    if os.path.exists(root_idb_dir):
        os.makedirs(default_idb_dir, exist_ok=True)
        try:
            for item in os.listdir(root_idb_dir):
                r_item = os.path.join(root_idb_dir, item)
                d_item = os.path.join(default_idb_dir, item)
                if os.path.isdir(r_item):
                    if not os.path.exists(d_item) or _get_dir_mtime(r_item) > _get_dir_mtime(d_item) + 2:
                        shutil.copytree(r_item, d_item, dirs_exist_ok=True)
        except Exception:
            pass

    if os.path.exists(default_idb_dir):
        os.makedirs(root_idb_dir, exist_ok=True)
        try:
            for item in os.listdir(default_idb_dir):
                r_item = os.path.join(root_idb_dir, item)
                d_item = os.path.join(default_idb_dir, item)
                if os.path.isdir(d_item):
                    if not os.path.exists(r_item) or _get_dir_mtime(d_item) > _get_dir_mtime(r_item) + 2:
                        shutil.copytree(d_item, r_item, dirs_exist_ok=True)
        except Exception:
            pass

    # 3. Sync Local Storage (leveldb tokens)
    root_ls = os.path.join(user_data_dir, "Local Storage")
    default_ls = os.path.join(user_data_dir, "Default", "Local Storage")

    if os.path.exists(root_ls) and not os.path.exists(default_ls):
        try:
            shutil.copytree(root_ls, default_ls, dirs_exist_ok=True)
        except Exception:
            pass
    elif os.path.exists(root_ls) and os.path.exists(default_ls):
        try:
            if _get_dir_mtime(root_ls) > _get_dir_mtime(default_ls) + 2:
                shutil.copytree(root_ls, default_ls, dirs_exist_ok=True)
            elif _get_dir_mtime(default_ls) > _get_dir_mtime(root_ls) + 2:
                shutil.copytree(default_ls, root_ls, dirs_exist_ok=True)
        except Exception:
            pass

    # 4. Sync Web Data and Login Data (credentials/autofill)
    for db_name in ("Login Data", "Web Data"):
        r_db = os.path.join(user_data_dir, db_name)
        d_db = os.path.join(user_data_dir, "Default", db_name)
        if os.path.exists(r_db) and not os.path.exists(d_db):
            try:
                shutil.copy2(r_db, d_db)
            except Exception:
                pass
        elif os.path.exists(d_db) and not os.path.exists(r_db):
            try:
                shutil.copy2(d_db, r_db)
            except Exception:
                pass

    # 5. Clean up any accidental sub-profile Local State to prevent duplicate profile creation
    bad_ls = os.path.join(user_data_dir, "Local State")
    if os.path.exists(bad_ls):
        try:
            os.remove(bad_ls)
        except Exception:
            pass


def brand_job_agent_profile(user_data_dir: str):
    """No-op: Prevents generating synthetic Local State files that trigger duplicate Edge profiles."""
    return


def clone_profile_for_fallback(src_dir: str, dst_dir: str):
    """
    Clones essential cookies, IndexedDB, and branding from the persistent profile into
    a temporary fallback directory when a process lock prevents direct binding.
    """
    if not src_dir or not os.path.exists(src_dir) or not dst_dir:
        return

    # First sync storage within src_dir to ensure Default has latest data
    try:
        sync_profile_storage(src_dir)
    except Exception:
        pass

    # 1. Copy Cookies (prefer whichever file has higher cookie count or newer timestamp)
    c1 = os.path.join(src_dir, "Network", "Cookies")
    c2 = os.path.join(src_dir, "Default", "Network", "Cookies")
    chosen_cookie = None
    if os.path.exists(c1) and os.path.exists(c2):
        if _get_cookie_count(c1) >= _get_cookie_count(c2):
            chosen_cookie = c1
        else:
            chosen_cookie = c2
    elif os.path.exists(c1):
        chosen_cookie = c1
    elif os.path.exists(c2):
        chosen_cookie = c2

    if chosen_cookie and os.path.exists(chosen_cookie) and os.path.getsize(chosen_cookie) > 0:
        target = os.path.join(dst_dir, "Default", "Network", "Cookies")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        try:
            shutil.copy2(chosen_cookie, target)
            for ext in ("-journal", "-wal", "-shm"):
                cj = chosen_cookie + ext
                tj = target + ext
                if os.path.exists(cj):
                    shutil.copy2(cj, tj)
        except Exception:
            pass

    # 2. Copy all IndexedDB folders
    for base_idb in (os.path.join(src_dir, "IndexedDB"), os.path.join(src_dir, "Default", "IndexedDB")):
        if os.path.exists(base_idb):
            try:
                for item in os.listdir(base_idb):
                    src_item = os.path.join(base_idb, item)
                    dst_item = os.path.join(dst_dir, "Default", "IndexedDB", item)
                    if os.path.isdir(src_item) and not os.path.exists(dst_item):
                        shutil.copytree(src_item, dst_item, dirs_exist_ok=True)
            except Exception:
                pass

    # 3. Copy Local Storage
    for base_ls in (os.path.join(src_dir, "Local Storage"), os.path.join(src_dir, "Default", "Local Storage")):
        if os.path.exists(base_ls):
            try:
                dst_ls = os.path.join(dst_dir, "Default", "Local Storage")
                if not os.path.exists(dst_ls):
                    shutil.copytree(base_ls, dst_ls, dirs_exist_ok=True)
            except Exception:
                pass

    # 4. Brand profile
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
