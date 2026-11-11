import os
import sys
import re
import json
import time
import logging
import threading
import socket
import shutil
import subprocess
import contextlib
import requests
from typing import Optional, Dict, Any, List

# Ensure project root is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

def scrape_job_from_url(*args, **kwargs):
    from scrapers.link_scraper import scrape_job_from_url as _scrape
    return _scrape(*args, **kwargs)

from core.database import save_or_update_job, get_job_by_url, get_job_by_id, delete_job_by_id

logger = logging.getLogger("whatsapp_bot")

STATE_FILE = os.path.join(BASE_DIR, "output", "whatsapp_state.json")
URL_REGEX = re.compile(r'https?://[^\s<>"]+|www\.[^\s<>"]+')

_new_jobs_lock = threading.Lock()
_unreported_new_jobs: List[str] = []


def record_new_whatsapp_job(title: str) -> None:
    with _new_jobs_lock:
        _unreported_new_jobs.append(title)


def get_and_clear_new_whatsapp_jobs() -> List[str]:
    with _new_jobs_lock:
        jobs = list(_unreported_new_jobs)
        _unreported_new_jobs.clear()
        return jobs


def get_state() -> Dict[str, Any]:
    """Loads persistent WhatsApp state from output/whatsapp_state.json."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Error reading {STATE_FILE}: {e}")
    return {"last_message_id": 0, "queued_messages": [], "processed_ids": []}


def save_state(state: Dict[str, Any]) -> None:
    """Saves persistent WhatsApp state."""
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        temp_file = STATE_FILE + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        os.replace(temp_file, STATE_FILE)
    except Exception as e:
        logger.error(f"Failed to save WhatsApp state: {e}")


def clean_url(url_match: str) -> str:
    """Trims trailing punctuation attached to URLs in chat messages."""
    url = url_match.strip()
    while url and url[-1] in ".,;:!?)'\"<>":
        url = url[:-1]
    if url.startswith("www."):
        url = "https://" + url
    return url


def normalize_phone_number(raw_phone: str) -> str:
    """Normalizes phone string to international E.164 digits format."""
    if not raw_phone:
        return ""
    digits = re.sub(r'\D', '', str(raw_phone))
    if not digits:
        return ""
    if digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("0") and len(digits) == 11:
        # Egyptian domestic mobile default e.g. 010... -> 2010...
        digits = "20" + digits[1:]
    return f"+{digits}"


def get_candidate_phone() -> str:
    """Returns candidate's phone number from config, .env, or candidate_profile.json."""
    try:
        from core import config as app_config
        phone = getattr(app_config, "WHATSAPP_PHONE_NUMBER", None)
        if phone and str(phone).strip():
            return normalize_phone_number(str(phone).strip())
    except Exception:
        pass

    env_phone = os.getenv("WHATSAPP_PHONE_NUMBER", "").strip()
    if env_phone:
        return normalize_phone_number(env_phone)

    try:
        from core.applicant_profile import load_profile
        prof = load_profile()
        profile_phone = prof.get("personal_info", {}).get("phone", "").strip()
        if profile_phone:
            return normalize_phone_number(profile_phone)
    except Exception:
        pass

    return ""


def send_whatsapp_message(
    phone: str,
    text: str,
    api_token: Optional[str] = None,
    phone_number_id: Optional[str] = None
) -> bool:
    """
    Sends WhatsApp text message to candidate strictly via Meta WhatsApp Cloud API.
    """
    clean_phone = normalize_phone_number(phone)
    if not clean_phone:
        logger.warning("Cannot send WhatsApp message: phone number is empty.")
        return False

    token = api_token or os.getenv("WHATSAPP_API_TOKEN")
    phone_id = phone_number_id or os.getenv("WHATSAPP_PHONE_NUMBER_ID")

    try:
        from core import config as app_config
        token = token or getattr(app_config, "WHATSAPP_API_TOKEN", None)
        phone_id = phone_id or getattr(app_config, "WHATSAPP_PHONE_NUMBER_ID", None)
    except Exception:
        pass

    if not token or not phone_id:
        logger.warning("WhatsApp Cloud API credentials missing (WHATSAPP_API_TOKEN or WHATSAPP_PHONE_NUMBER_ID not set).")
        return False

    url = f"https://graph.facebook.com/v18.0/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": clean_phone.lstrip("+"),
        "type": "text",
        "text": {"body": text}
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=12)
        if resp.status_code in (200, 201):
            logger.info(f"Dispatched WhatsApp notification via Cloud API to {clean_phone}.")
            return True
        logger.warning(f"WhatsApp Cloud API responded with {resp.status_code}: {resp.text}")
        return False
    except Exception as e:
        logger.error(f"WhatsApp Cloud API dispatch error: {e}")
        return False


def notify_whatsapp_candidate(message: str) -> bool:
    """Dispatches real-time notification to candidate on WhatsApp."""
    try:
        phone = get_candidate_phone()
        if phone:
            return send_whatsapp_message(phone=phone, text=message)
        logger.debug("WhatsApp candidate notification skipped: No phone number configured.")
    except Exception as e:
        logger.debug(f"Failed to notify WhatsApp candidate: {e}")
    return False


def _extract_job_urls(text: str) -> List[str]:
    """Extracts and normalizes all valid URLs from message text."""
    found_urls = URL_REGEX.findall(text or "")
    return [clean_url(u) for u in found_urls if len(clean_url(u)) > 8]


def _scrape_and_persist_url(
    job_url: str,
    is_scholarship: bool,
    is_liked: bool,
    is_applied: bool,
    force_pending: bool
) -> Dict[str, Any]:
    """Scrapes a single job URL, resolves duplicates, and persists to DB."""
    logger.info(f"WhatsApp bot processing job URL: {job_url} (scholarship={is_scholarship}, liked={is_liked}, applied={is_applied})")

    # 1. Fast pre-scrape duplicate check: URL already in DB?
    existing = get_job_by_url(job_url)
    if existing:
        if is_liked or is_applied or is_scholarship:
            upd = dict(existing)
            if is_scholarship:
                upd["job_type"] = "Scholarship"
            if is_liked:
                upd["status"] = "liked"
            if is_applied:
                upd["is_applied"] = 1
            saved_job, _ = save_or_update_job(upd, force_pending=False)
            logger.info(f"WhatsApp bot updated existing job: {saved_job.get('title')}")
            return {
                "status": "updated",
                "title": saved_job.get("title") or "Existing Job",
                "company": saved_job.get("company") or "Unknown Company",
                "score": round(saved_job.get("relevance_score", 0), 1),
                "url": job_url,
                "is_scholarship": saved_job.get("job_type") == "Scholarship",
                "is_liked": saved_job.get("status") == "liked",
                "is_applied": saved_job.get("is_applied") == 1
            }

        logger.info(f"WhatsApp bot skipped duplicate job URL: {job_url}")
        return {
            "status": "duplicate",
            "title": existing.get("title") or "Existing Job",
            "company": existing.get("company") or "Unknown Company",
            "score": round(existing.get("relevance_score", 0), 1),
            "url": job_url,
            "is_scholarship": is_scholarship or existing.get("job_type") == "Scholarship",
            "is_liked": existing.get("status") == "liked",
            "is_applied": existing.get("is_applied") == 1
        }

    try:
        job_dict = scrape_job_from_url(url=job_url, scraper_type="auto", is_scholarship=is_scholarship)
        if is_liked:
            job_dict["status"] = "liked"
        if is_applied:
            job_dict["is_applied"] = 1

        # 2. Check if job_id already in DB
        if job_dict.get("job_id"):
            existing_by_id = get_job_by_id(job_dict["job_id"])
            if existing_by_id:
                if is_liked or is_applied or is_scholarship:
                    upd = dict(existing_by_id)
                    if is_scholarship:
                        upd["job_type"] = "Scholarship"
                    if is_liked:
                        upd["status"] = "liked"
                    if is_applied:
                        upd["is_applied"] = 1
                    saved_job, _ = save_or_update_job(upd, force_pending=False)
                    return {
                        "status": "updated",
                        "title": saved_job.get("title") or "Existing Job",
                        "company": saved_job.get("company") or "Unknown Company",
                        "score": round(saved_job.get("relevance_score", 0), 1),
                        "url": job_url,
                        "is_scholarship": saved_job.get("job_type") == "Scholarship",
                        "is_liked": saved_job.get("status") == "liked",
                        "is_applied": saved_job.get("is_applied") == 1
                    }

                logger.info(f"WhatsApp bot skipped duplicate job_id: {job_dict['job_id']}")
                return {
                    "status": "duplicate",
                    "title": existing_by_id.get("title") or "Existing Job",
                    "company": existing_by_id.get("company") or "Unknown Company",
                    "score": round(existing_by_id.get("relevance_score", 0), 1),
                    "url": job_url,
                    "is_scholarship": is_scholarship or existing_by_id.get("job_type") == "Scholarship",
                    "is_liked": existing_by_id.get("status") == "liked",
                    "is_applied": existing_by_id.get("is_applied") == 1
                }

        saved_job, is_new = save_or_update_job(job_dict, force_pending=force_pending)
        title = saved_job.get("title") or "Unknown Title"
        company = saved_job.get("company") or "Unknown Company"
        location = saved_job.get("location") or "Not Specified"
        score = round(saved_job.get("relevance_score", 0), 1)

        if is_new:
            record_new_whatsapp_job(title)
            return {
                "status": "added",
                "title": title,
                "company": company,
                "location": location,
                "score": score,
                "url": job_url,
                "is_scholarship": is_scholarship or saved_job.get("job_type") == "Scholarship",
                "is_liked": saved_job.get("status") == "liked",
                "is_applied": saved_job.get("is_applied") == 1,
                "job_data": saved_job
            }
        return {
            "status": "duplicate",
            "title": title,
            "company": company,
            "score": score,
            "url": job_url,
            "is_scholarship": is_scholarship or saved_job.get("job_type") == "Scholarship",
            "is_liked": saved_job.get("status") == "liked",
            "is_applied": saved_job.get("is_applied") == 1
        }
    except Exception as e:
        logger.error(f"Failed to scrape job from URL '{job_url}': {e}", exc_info=True)
        return {
            "status": "error",
            "url": job_url,
            "error": str(e)
        }


def _parse_and_persist_raw_text(
    text: str,
    is_scholarship: bool,
    is_liked: bool,
    is_applied: bool,
    force_pending: bool
) -> Dict[str, Any]:
    """Parses raw job description text with LLM/regex, scores, and persists to DB."""
    logger.info(f"WhatsApp bot processing raw job text (scholarship={is_scholarship}, liked={is_liked}, applied={is_applied})")
    try:
        clean_text = re.sub(r'[#/](?:scholarships?|fellowships?|liked?|applied)\b', '', text, flags=re.IGNORECASE).strip()
        parse_text = clean_text if len(clean_text) >= 15 else text

        job_dict = scrape_job_from_url(url="", raw_text=parse_text, scraper_type="generic", is_scholarship=is_scholarship)
        if is_liked:
            job_dict["status"] = "liked"
        if is_applied:
            job_dict["is_applied"] = 1

        job_id = job_dict.get("job_id")
        if job_id:
            existing = get_job_by_id(job_id)
            if existing:
                if is_liked or is_applied or is_scholarship:
                    upd = dict(existing)
                    if is_scholarship:
                        upd["job_type"] = "Scholarship"
                    if is_liked:
                        upd["status"] = "liked"
                    if is_applied:
                        upd["is_applied"] = 1
                    saved_job, _ = save_or_update_job(upd, force_pending=False)
                    return {
                        "status": "updated",
                        "title": saved_job.get("title") or "Existing Job",
                        "company": saved_job.get("company") or "Unknown Company",
                        "score": round(saved_job.get("relevance_score", 0), 1),
                        "is_scholarship": saved_job.get("job_type") == "Scholarship",
                        "is_liked": saved_job.get("status") == "liked",
                        "is_applied": saved_job.get("is_applied") == 1
                    }

                logger.info(f"WhatsApp bot skipped duplicate raw text job: {existing.get('title')}")
                return {
                    "status": "duplicate",
                    "title": existing.get("title") or "Existing Job",
                    "company": existing.get("company") or "Unknown Company",
                    "score": round(existing.get("relevance_score", 0), 1),
                    "is_scholarship": is_scholarship or existing.get("job_type") == "Scholarship",
                    "is_liked": existing.get("status") == "liked",
                    "is_applied": existing.get("is_applied") == 1
                }

        score = round(job_dict.get("relevance_score", 0), 1)
        title = job_dict.get("title") or "Extracted Role"
        company = job_dict.get("company") or "Extracted Company"
        location = job_dict.get("location") or "Not Specified"

        if not is_liked and not is_applied and not is_scholarship and score <= 0:
            delete_job_by_id(job_dict.get("job_id"))
            return {
                "status": "pruned",
                "title": title,
                "company": company,
                "location": location,
                "score": score,
                "is_scholarship": False,
                "is_liked": False,
                "is_applied": False
            }

        saved_job, is_new = save_or_update_job(job_dict, force_pending=force_pending)
        title = saved_job.get("title") or "Extracted Role"
        company = saved_job.get("company") or "Extracted Company"
        location = saved_job.get("location") or "Not Specified"
        score = round(saved_job.get("relevance_score", 0), 1)

        if is_new:
            record_new_whatsapp_job(title)
            return {
                "status": "added",
                "title": title,
                "company": company,
                "location": location,
                "score": score,
                "is_scholarship": is_scholarship or saved_job.get("job_type") == "Scholarship",
                "is_liked": saved_job.get("status") == "liked",
                "is_applied": saved_job.get("is_applied") == 1,
                "job_data": saved_job
            }
        return {
            "status": "duplicate",
            "title": title,
            "company": company,
            "score": score,
            "is_scholarship": is_scholarship or saved_job.get("job_type") == "Scholarship",
            "is_liked": saved_job.get("status") == "liked",
            "is_applied": saved_job.get("is_applied") == 1
        }
    except Exception as e:
        logger.error(f"Failed to parse raw job text: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e)
        }


def send_summary_reply(phone: str, results: List[Dict[str, Any]]) -> None:
    """Sends a consolidated WhatsApp summary message for processed jobs."""
    if not results or not phone:
        return

    job_results = [r for r in results if r.get("status") in ("added", "updated", "duplicate", "pruned", "error")]
    if not job_results:
        return

    if len(job_results) == 1:
        res = job_results[0]
        st = res.get("status")
        is_schol = res.get("is_scholarship")
        is_app = res.get("is_applied")
        is_lk = res.get("is_liked")
        entity_name = "Scholarship" if is_schol else "Job"

        if st in ("added", "updated"):
            verb = "Saved" if st == "added" else "Updated"
            status_text = "Marked as Applied" if is_app else ("Liked & Pinned" if is_lk else "Added to Pending")
            reply = (
                f"✅ *{entity_name} {verb}! ({status_text})*\n\n"
                f"📌 *Role:* {res.get('title')}\n"
                f"🏢 *Company:* {res.get('company')}\n"
                f"🎯 *Match Score:* {res.get('score')}%\n"
            )
            if res.get("location"):
                reply += f"📍 *Location:* {res.get('location')}\n"
            send_whatsapp_message(phone, reply.strip())
        elif st == "duplicate":
            reply = (
                f"ℹ️ *{entity_name} Already in Database*\n\n"
                f"📌 *Role:* {res.get('title')}\n"
                f"🏢 *Company:* {res.get('company')}\n"
                f"🎯 *Match Score:* {res.get('score')}%\n"
                f"_Skipped duplicate scrape._"
            )
            send_whatsapp_message(phone, reply)
    else:
        added = [r for r in job_results if r.get("status") == "added"]
        dups = [r for r in job_results if r.get("status") == "duplicate"]
        reply = f"📥 *WhatsApp Batch Intake Summary*\n\n✅ Added: {len(added)}\nℹ️ Duplicates: {len(dups)}\n"
        for r in added[:5]:
            reply += f"• {r.get('title')} ({r.get('company', 'Unknown')}) - {r.get('score')}%\n"
        if len(added) > 5:
            reply += f"_...and {len(added) - 5} more._"
        send_whatsapp_message(phone, reply.strip())


def process_message(
    message: Dict[str, Any],
    candidate_phone: Optional[str] = None,
    send_reply: bool = True
) -> List[Dict[str, Any]]:
    """
    Processes an incoming WhatsApp message payload or string:
    1. Checks authorization against configured candidate phone.
    2. Detects URLs vs Raw Text.
    3. Scrapes & scores job opportunities.
    4. Persists to SQLite.
    5. Optionally dispatches WhatsApp confirmation reply.
    """
    configured_phone = normalize_phone_number(candidate_phone or get_candidate_phone())
    sender_phone = normalize_phone_number(message.get("from") or message.get("phone") or "")

    if configured_phone and sender_phone and configured_phone != sender_phone:
        logger.warning(f"Blocked unauthorized WhatsApp message from {sender_phone} (expected {configured_phone}).")
        return []

    text = (message.get("text") or message.get("body") or message.get("caption") or "").strip()
    if not text:
        return []

    results: List[Dict[str, Any]] = []
    is_scholarship = bool(re.search(r'(?:[#/]scholarships?|[#/]fellowships?|\bمنحة\b|\bمنح\b)', text, re.IGNORECASE))
    is_applied = bool(re.search(r'(?:[#/]applied|\bقدّمت\b|\bقدمت\b)', text, re.IGNORECASE))
    is_liked = bool(re.search(r'(?:[#/]liked?|[#/]favorite|\bإعجاب\b|\bاعجاب\b)', text, re.IGNORECASE)) or is_applied
    force_pending = False if is_liked else True

    found_urls = _extract_job_urls(text)
    # Check for hidden URLs (e.g. [text](url))
    markdown_links = re.findall(r'\[([^\]]+)\]\((https?://[^\)]+)\)', text)
    for _, md_url in markdown_links:
        cleaned_md = clean_url(md_url)
        if cleaned_md not in found_urls:
            found_urls.append(cleaned_md)

    if found_urls:
        for job_url in found_urls:
            res = _scrape_and_persist_url(job_url, is_scholarship, is_liked, is_applied, force_pending)
            results.append(res)
    else:
        if len(text) < 15:
            if send_reply and (sender_phone or configured_phone):
                send_whatsapp_message(
                    sender_phone or configured_phone,
                    "ℹ️ Please share a job link (e.g. LinkedIn or Wuzzuf) or paste a complete job description text."
                )
            return []
        res = _parse_and_persist_raw_text(text, is_scholarship, is_liked, is_applied, force_pending)
        results.append(res)

    if send_reply and results and (sender_phone or configured_phone):
        send_summary_reply(sender_phone or configured_phone, results)

    return results


def enqueue_incoming_message(sender: str, text: str, message_id: Optional[str] = None) -> None:
    """Queues an incoming message from webhook or local receiver for one-shot batch sync."""
    state = get_state()
    queued = state.get("queued_messages", [])
    m_id = message_id or f"msg_{int(time.time() * 1000)}"
    queued.append({
        "id": m_id,
        "from": sender,
        "text": text,
        "timestamp": int(time.time())
    })
    state["queued_messages"] = queued
    save_state(state)


def process_incoming_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Handles standard Meta WhatsApp Cloud API or Twilio incoming webhook payloads."""
    results = []
    # 1. Meta WhatsApp Cloud API format
    try:
        entries = payload.get("entry", [])
        for entry in entries:
            changes = entry.get("changes", [])
            for change in changes:
                value = change.get("value", {})
                messages = value.get("messages", [])
                for msg in messages:
                    sender = msg.get("from", "")
                    msg_id = msg.get("id", "")
                    body = ""
                    if msg.get("type") == "text":
                        body = msg.get("text", {}).get("body", "")
                    elif msg.get("type") == "button":
                        body = msg.get("button", {}).get("text", "")
                    if body:
                        enqueue_incoming_message(sender=sender, text=body, message_id=msg_id)
                        res = process_message({"from": sender, "text": body, "id": msg_id}, send_reply=True)
                        results.extend(res)
                        if msg_id:
                            st = get_state()
                            p_ids = set(st.get("processed_ids", []))
                            p_ids.add(msg_id)
                            st["processed_ids"] = list(p_ids)[-500:]
                            st["queued_messages"] = [m for m in st.get("queued_messages", []) if m.get("id") != msg_id]
                            save_state(st)
    except Exception as e:
        logger.warning(f"Error extracting Meta webhook payload: {e}")

    # 2. Twilio or Direct payload format
    if "From" in payload or "from" in payload:
        sender = payload.get("From") or payload.get("from")
        body = payload.get("Body") or payload.get("body") or payload.get("text")
        m_id = payload.get("MessageSid") or payload.get("id")
        if body:
            enqueue_incoming_message(sender=str(sender), text=str(body), message_id=str(m_id) if m_id else None)
            res = process_message({"from": str(sender), "text": str(body)}, send_reply=True)
            results.extend(res)
            if m_id:
                st = get_state()
                p_ids = set(st.get("processed_ids", []))
                p_ids.add(str(m_id))
                st["processed_ids"] = list(p_ids)[-500:]
                st["queued_messages"] = [m for m in st.get("queued_messages", []) if m.get("id") != str(m_id)]
                save_state(st)

    return results


_tunnel_sync_lock = threading.Lock()


def resolve_ngrok_bin() -> Optional[str]:
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


def is_port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.25) -> bool:
    """Checks whether a local TCP port is actively listening."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        try:
            return s.connect_ex((host, port)) == 0
        except Exception:
            return False


@contextlib.contextmanager
def managed_local_server(port: int = 8000, timeout: float = 5.0):
    """
    Context manager ensuring local HTTP server is listening on port 8000 to accept webhooks.
    - If port 8000 is already open (e.g. desktop app or uvicorn is running), reuses it.
    - If port 8000 is not open, spawns a temporary uvicorn subprocess and shuts it down on exit.
    """
    if is_port_open(port):
        yield {"server_active": True, "reused_server": True, "process": None}
        return

    logger.info(f"Local server on port {port} is not running. Starting temporary listener for webhook intake...")
    python_exe = sys.executable.replace("pythonw.exe", "python.exe").replace("job-agent-w.exe", "job-agent.exe")
    creationflags = 0x08000000 if sys.platform == "win32" else 0
    cmd = [python_exe, "-m", "uvicorn", "web.app:app", "--host", "127.0.0.1", "--port", str(port)]
    proc = None
    started = False
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=BASE_DIR,
            creationflags=creationflags
        )
        start_t = time.time()
        while time.time() - start_t < timeout:
            if is_port_open(port):
                started = True
                break
            if proc.poll() is not None:
                break
            time.sleep(0.1)

        yield {"server_active": started, "reused_server": False, "process": proc}
    finally:
        if proc and proc.poll() is None:
            logger.info(f"Shutting down temporary local listener on port {port}...")
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except (subprocess.TimeoutExpired, Exception):
                try:
                    proc.kill()
                except Exception:
                    pass


@contextlib.contextmanager
def managed_ngrok_tunnel(local_port: int = 8000, domain: Optional[str] = None, timeout: float = 5.0):
    """
    Context manager for on-demand ngrok tunnel lifecycle.
    - Reuses existing external tunnel if port 4040 is already open and NEVER terminates it.
    - Otherwise, starts an ngrok tunnel subprocess and terminates it immediately on context exit.
    """
    external_tunnel = is_port_open(4040)
    if external_tunnel:
        logger.info("External ngrok tunnel detected on port 4040. Reusing external tunnel without termination.")
        yield {"tunnel_active": True, "reused_external": True, "domain": domain, "process": None}
        return

    target_domain = domain
    if not target_domain:
        try:
            from core import config as app_config
            target_domain = getattr(app_config, "NGROK_DOMAIN", "") or os.getenv("NGROK_DOMAIN", "")
        except Exception:
            target_domain = os.getenv("NGROK_DOMAIN", "")

    ngrok_bin = resolve_ngrok_bin()
    if not ngrok_bin or not target_domain:
        logger.debug(f"ngrok on-demand tunnel skipped: bin={ngrok_bin}, domain={target_domain}")
        yield {"tunnel_active": False, "reused_external": False, "domain": target_domain, "process": None}
        return

    logger.info(f"Starting on-demand ngrok tunnel for port {local_port} (domain: {target_domain})...")
    creationflags = 0x08000000 if sys.platform == "win32" else 0
    cmd = [ngrok_bin, "http", str(local_port), f"--url={target_domain}"]
    proc = None
    started = False
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags
        )
        start_t = time.time()
        while time.time() - start_t < timeout:
            if is_port_open(4040):
                started = True
                break
            if proc.poll() is not None:
                logger.warning(f"ngrok process exited prematurely with code {proc.returncode}")
                break
            time.sleep(0.1)

        if started:
            logger.info("On-demand ngrok tunnel successfully established on port 4040.")
        else:
            logger.warning("Timed out waiting for on-demand ngrok tunnel on port 4040.")

        yield {"tunnel_active": started, "reused_external": False, "domain": target_domain, "process": proc}
    finally:
        if proc and proc.poll() is None:
            logger.info("Shutting down on-demand ngrok tunnel...")
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except (subprocess.TimeoutExpired, Exception):
                try:
                    proc.kill()
                except Exception:
                    pass
            logger.info("On-demand ngrok tunnel terminated.")


def _process_whatsapp_queue(candidate_phone: Optional[str] = None) -> Dict[str, Any]:
    """Processes messages buffered in whatsapp_state.json and aggregates with any webhook additions."""
    phone = candidate_phone or get_candidate_phone()
    state = get_state()
    queued = state.get("queued_messages", [])
    processed_ids = set(state.get("processed_ids", []))

    batch_results: List[Dict[str, Any]] = []
    unprocessed_queue = []

    for msg in queued:
        m_id = msg.get("id")
        if m_id and m_id in processed_ids:
            continue
        try:
            res = process_message(msg, candidate_phone=phone, send_reply=False)
            if res:
                batch_results.extend(res)
            if m_id:
                processed_ids.add(m_id)
        except Exception as e:
            logger.error(f"Error processing queued WhatsApp message {m_id}: {e}", exc_info=True)
            unprocessed_queue.append(msg)

    state["queued_messages"] = unprocessed_queue
    state["processed_ids"] = list(processed_ids)[-500:]  # Keep last 500 IDs to bound size
    save_state(state)

    if batch_results and phone:
        send_summary_reply(phone, batch_results)

    added_titles = [r["title"] for r in batch_results if r.get("status") == "added"]
    added_records = [r["job_data"] for r in batch_results if r.get("status") == "added" and "job_data" in r]
    dup_count = sum(1 for r in batch_results if r.get("status") == "duplicate")

    # Ingest any new jobs recorded during this fetch cycle (e.g. from active webhook)
    for title in get_and_clear_new_whatsapp_jobs():
        if title not in added_titles:
            added_titles.append(title)

    status_str = "success" if (added_titles or dup_count > 0) else "no_updates"

    logger.info(f"WhatsApp sync complete: {len(added_titles)} added, {dup_count} duplicate(s).")
    return {
        "count": len(added_titles),
        "jobs": added_titles,
        "job_records": added_records,
        "duplicates": dup_count,
        "status": status_str
    }


def sync_queued_whatsapp_jobs(
    candidate_phone: Optional[str] = None,
    manage_tunnel: bool = True,
    ingress_timeout: Optional[float] = None,
    local_port: int = 8000
) -> Dict[str, Any]:
    """
    Performs on-demand synchronization of WhatsApp messages:
    - If manage_tunnel is True:
        1. Ensures local HTTP server is listening on local_port.
        2. Spins up ngrok tunnel on-demand (reusing external tunnel if already open on 4040).
        3. Waits for ingress window to allow Meta's retrying webhooks to deliver pending messages.
        4. Processes all queued messages.
        5. Shuts down the on-demand tunnel immediately after processing (external tunnels preserved).
    - If manage_tunnel is False: processes local queued messages directly without tunnel lifecycle.
    """
    if not manage_tunnel:
        return _process_whatsapp_queue(candidate_phone=candidate_phone)

    timeout_val = ingress_timeout
    if timeout_val is None:
        try:
            timeout_val = float(os.getenv("WHATSAPP_INGRESS_TIMEOUT", "3.0"))
        except (ValueError, TypeError):
            timeout_val = 3.0

    with _tunnel_sync_lock:
        with managed_local_server(port=local_port):
            with managed_ngrok_tunnel(local_port=local_port) as tunnel_info:
                if tunnel_info.get("tunnel_active") and timeout_val > 0:
                    logger.info(f"Tunnel active. Ingesting pending WhatsApp webhook messages for {timeout_val}s...")
                    time.sleep(timeout_val)
                return _process_whatsapp_queue(candidate_phone=candidate_phone)
