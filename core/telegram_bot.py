import os
import sys
import re
import json
import time
import logging
import threading
import requests
from typing import Optional, Dict, Any, List

# Ensure project root is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from scrapers.link_scraper import scrape_job_from_url
from core.database import save_or_update_job, get_job_by_url, get_job_by_id, delete_job_by_id

logger = logging.getLogger("telegram_bot")

STATE_FILE = os.path.join(BASE_DIR, "output", "telegram_state.json")
URL_REGEX = re.compile(r'https?://[^\s<>"]+|www\.[^\s<>"]+')

_bot_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()

_new_jobs_lock = threading.Lock()
_unreported_new_jobs: List[str] = []

def record_new_telegram_job(title: str) -> None:
    with _new_jobs_lock:
        _unreported_new_jobs.append(title)

def get_and_clear_new_telegram_jobs() -> List[str]:
    with _new_jobs_lock:
        jobs = list(_unreported_new_jobs)
        _unreported_new_jobs.clear()
        return jobs


def get_state() -> Dict[str, Any]:
    """Loads persistent Telegram state from output/telegram_state.json."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Error reading {STATE_FILE}: {e}")
    return {"last_update_id": 0}


def save_state(state: Dict[str, Any]) -> None:
    """Saves persistent Telegram state."""
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        temp_file = STATE_FILE + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        os.replace(temp_file, STATE_FILE)
    except Exception as e:
        logger.error(f"Failed to save Telegram state: {e}")


def send_message(bot_token: str, chat_id: int | str, text: str, parse_mode: Optional[str] = None) -> bool:
    """Sends a text message to a Telegram chat."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    try:
        resp = requests.post(url, json=payload, timeout=15)
        data = resp.json()
        if not data.get("ok"):
            logger.warning(f"Telegram sendMessage error: {data.get('description')}")
            # Fallback without parse_mode if formatting error occurred
            if parse_mode:
                payload.pop("parse_mode", None)
                requests.post(url, json=payload, timeout=10)
        return bool(data.get("ok"))
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
        return False


def send_chat_action(bot_token: str, chat_id: int | str, action: str = "typing") -> None:
    """Sends a chat action status like 'typing' to show user something is happening."""
    url = f"https://api.telegram.org/bot{bot_token}/sendChatAction"
    try:
        requests.post(url, json={"chat_id": chat_id, "action": action}, timeout=5)
    except Exception:
        pass


def clean_url(url_match: str) -> str:
    """Trims trailing punctuation sometimes attached to URLs in chat messages."""
    url = url_match.strip()
    while url and url[-1] in ".,;:!?)'\"<>":
        url = url[:-1]
    if url.startswith("www."):
        url = "https://" + url
    return url


def html_escape(text: Any) -> str:
    """Escapes HTML special characters for Telegram HTML parse_mode."""
    if text is None:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def send_summary_reply(bot_token: str, chat_id: str, results: List[Dict[str, Any]]) -> None:
    """
    Sends a consolidated summary message using HTML formatting:
    - If 1 job processed: Clean single-job card (Added / Duplicate / Error).
    - If multiple jobs processed (queued backlog): ONE single grouped batch message.
    """
    if not results or not chat_id:
        return

    # Filter out empty or unhandled statuses
    job_results = [r for r in results if r.get("status") in ("added", "updated", "duplicate", "pruned", "error")]
    if not job_results:
        return

    total = len(job_results)
    if total == 1:
        res = job_results[0]
        st = res.get("status")
        is_schol = res.get("is_scholarship") or res.get("job_type") == "Scholarship"
        is_app = res.get("is_applied")
        is_lk = res.get("is_liked")
        entity_name = "Scholarship" if is_schol else "Job"

        if st in ("added", "updated"):
            verb = "Saved" if st == "added" else "Updated"
            if is_app:
                header = f"✅ <b>{entity_name} {verb} as Applied!</b>"
                footer = "Marked as Applied and saved in your dashboard."
            elif is_lk:
                header = f"❤️ <b>{entity_name} {verb} &amp; Liked!</b>"
                footer = "Pinned to your Liked opportunities in your dashboard."
            elif is_schol:
                header = f"🎓 <b>Scholarship {verb}!</b>"
                footer = "Added to your dashboard under Scholarships!"
            else:
                header = f"✅ <b>Job {verb}!</b>"
                footer = "Added to your Pending jobs list."

            reply = (
                f"{header}\n\n"
                f"📌 <b>{html_escape(res.get('title'))}</b>\n"
                f"🏢 {html_escape(res.get('company'))} | 📍 {html_escape(res.get('location', 'Not specified'))}\n"
                f"⭐ <b>Match Score: {res.get('score')}%</b>\n\n"
                f"{footer}"
            )
        elif st == "duplicate":
            reply = (
                f"ℹ️ <b>{'Scholarship' if is_schol else 'Job'} Already in Database (Skipped)</b>\n\n"
                f"📌 <b>{html_escape(res.get('title'))}</b>\n"
                f"🏢 {html_escape(res.get('company'))}\n"
                f"⭐ <b>Match Score: {res.get('score')}%</b>\n\n"
                "Not rescored or re-added — existing record preserved."
            )
        elif st == "pruned":
            reply = (
                f"🗑️ <b>Job Dropped / Pruned (Score: {res.get('score')}%)</b>\n\n"
                f"📌 <b>{html_escape(res.get('title'))}</b>\n"
                f"🏢 {html_escape(res.get('company'))} | 📍 {html_escape(res.get('location', 'Not specified'))}\n"
                f"⭐ <b>Match Score: {res.get('score')}%</b>\n\n"
                f"This role scored 0% (does not match your career/location criteria) and was pruned from your dashboard.\n\n"
                f"💡 <i>Tip: If you want to keep this job, send it with <code>/liked</code>, <code>/applied</code>, or <code>/scholarship</code>.</i>"
            )
        else:
            err = res.get('error', 'Unknown error')
            reply = f"⚠️ <b>Failed to parse {'scholarship' if is_schol else 'job'}:</b>\n{html_escape(str(err)[:200])}"
        send_message(bot_token, chat_id, reply, parse_mode="HTML")
        return

    # Multiple jobs batch summary
    added = [r for r in job_results if r.get("status") in ("added", "updated")]
    duplicates = [r for r in job_results if r.get("status") == "duplicate"]
    pruned = [r for r in job_results if r.get("status") == "pruned"]
    errors = [r for r in job_results if r.get("status") == "error"]

    lines = [f"📥 <b>Finished Processing {total} Queued Jobs!</b>\n"]

    if added:
        lines.append(f"✅ <b>Added {len(added)} New Role{'s' if len(added) > 1 else ''}:</b>")
        for i, j in enumerate(added, 1):
            if j.get("is_applied"):
                tag_icon = "✅ "
            elif j.get("is_liked"):
                tag_icon = "❤️ "
            elif j.get("is_scholarship") or j.get("job_type") == "Scholarship":
                tag_icon = "🎓 "
            else:
                tag_icon = ""
            lines.append(f"{i}. {tag_icon}<b>{html_escape(j.get('title'))}</b> — {html_escape(j.get('company'))} ({j.get('score')}%)")
        lines.append("")

    if duplicates:
        lines.append(f"ℹ️ <b>{len(duplicates)} Repeated Job{'s' if len(duplicates) > 1 else ''} Skipped (Already in Database):</b>")
        for j in duplicates:
            lines.append(f"• {html_escape(j.get('title'))} — {html_escape(j.get('company'))}")
        lines.append("")

    if pruned:
        lines.append(f"🗑️ <b>{len(pruned)} Job{'s' if len(pruned) > 1 else ''} Pruned (Score ≤ 0):</b>")
        for j in pruned:
            lines.append(f"• <b>{html_escape(j.get('title'))}</b> — {html_escape(j.get('company'))} (0%)")
        lines.append("")

    if errors:
        lines.append(f"⚠️ <b>{len(errors)} Failed:</b>")
        for e in errors:
            err = e.get('error', 'Error')
            lines.append(f"• {html_escape(str(err)[:100])}")
        lines.append("")

    if added:
        lines.append("All new roles are ready in your desktop dashboard!")
    elif duplicates and not added:
        lines.append("All jobs were already saved in your database — skipped rescoring.")

    reply_text = "\n".join(lines).strip()
    send_message(bot_token, chat_id, reply_text, parse_mode="HTML")


_last_seen_chat: Optional[Dict[str, Any]] = None

def process_message(bot_token: str, message: Dict[str, Any], allowed_chat_id: Optional[str] = None, send_reply: bool = True) -> List[Dict[str, Any]]:
    """
    Processes a single message:
    1. Checks authorization.
    2. Detects URL vs Raw Text automatically.
    3. Checks for duplicates in database before scraping/scoring (no rescore, no readd).
    4. Scrapes & scores only new jobs.
    5. Saves to SQLite.
    6. Returns list of job results and optionally sends reply.
    """
    global _last_seen_chat
    chat = message.get("chat", {})
    chat_id = str(chat.get("id", ""))
    user = message.get("from", {})
    username = user.get("username", user.get("first_name", "User"))

    if chat_id:
        _last_seen_chat = {
            "chat_id": chat_id,
            "username": username,
            "text": (message.get("text") or message.get("caption") or "").strip()
        }
        try:
            state = get_state()
            state["last_seen_chat"] = _last_seen_chat
            save_state(state)
        except Exception:
            pass

    # Security check: If allowed_chat_id is specified, strictly enforce it
    if allowed_chat_id and str(allowed_chat_id).strip():
        if chat_id != str(allowed_chat_id).strip():
            logger.warning(f"Blocked unauthorized message from chat_id={chat_id} (@{username})")
            send_message(bot_token, chat_id, "⛔ Unauthorized: This Job Agent bot is configured for a private user.")
            return []

    text = (message.get("text") or message.get("caption") or "").strip()
    if not text:
        return []

    # Handle /start, /help or initial pairing
    if text.startswith("/start") or text.startswith("/help") or not allowed_chat_id:
        if not allowed_chat_id:
            welcome_text = (
                f"👋 <b>Welcome to Job Agent Mobile Sync!</b>\n\n"
                f"📱 Detected User: @{html_escape(username)}\n"
                f"🔑 Your Chat ID: <code>{html_escape(chat_id)}</code>\n\n"
                f"👉 Click <b>'Auto-Detect'</b> in the Job Agent Settings on your desktop to link your phone, or paste <code>{html_escape(chat_id)}</code> into the Chat ID box!"
            )
        else:
            welcome_text = (
                "👋 <b>Welcome to Job Agent Mobile Sync!</b>\n\n"
                "Whenever you find a job on your phone:\n"
                "• <b>Share or send a link</b> (LinkedIn, Wuzzuf, etc.)\n"
                "• <b>Or paste the post text</b> directly\n\n"
                "🏷️ <b>Quick Tags & Commands:</b>\n"
                "• <code>/scholarship</code> or <code>#scholarship</code> — Save as Scholarship 🎓\n"
                "• <code>/liked</code> or <code>#liked</code> — Save directly as Liked ❤️\n"
                "• <code>/applied</code> or <code>#applied</code> — Mark as Already Applied ✅\n\n"
                "You can combine tags too (e.g. <code>#scholarship #applied [link]</code>)!\n"
                "I will automatically parse the job, score it against your CV, and save it to your database."
            )
        send_message(bot_token, chat_id, welcome_text, parse_mode="HTML")
        return []

    send_chat_action(bot_token, chat_id, "typing")

    results: List[Dict[str, Any]] = []
    is_scholarship = bool(re.search(r'(?:[#/]scholarships?|[#/]fellowships?|\bمنحة\b|\bمنح\b)', text, re.IGNORECASE))
    is_applied = bool(re.search(r'(?:[#/]applied|\bقدّمت\b|\bقدمت\b)', text, re.IGNORECASE))
    is_liked = bool(re.search(r'(?:[#/]liked?|[#/]favorite|\bإعجاب\b|\bاعجاب\b)', text, re.IGNORECASE)) or is_applied

    force_pending = False if is_liked else True

    # Detect URLs in text
    found_urls = URL_REGEX.findall(text)
    urls = [clean_url(u) for u in found_urls if len(clean_url(u)) > 8]

    if urls:
        # User sent one or more links
        for job_url in urls:
            logger.info(f"Telegram bot processing job URL: {job_url} (scholarship={is_scholarship}, liked={is_liked}, applied={is_applied})")

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
                    logger.info(f"Telegram bot updated existing job: {saved_job.get('title')}")
                    results.append({
                        "status": "updated",
                        "title": saved_job.get("title") or "Existing Job",
                        "company": saved_job.get("company") or "Unknown Company",
                        "score": round(saved_job.get("relevance_score", 0), 1),
                        "url": job_url,
                        "is_scholarship": saved_job.get("job_type") == "Scholarship",
                        "is_liked": saved_job.get("status") == "liked",
                        "is_applied": saved_job.get("is_applied") == 1
                    })
                    continue

                logger.info(f"Telegram bot skipped duplicate job URL: {job_url}")
                results.append({
                    "status": "duplicate",
                    "title": existing.get("title") or "Existing Job",
                    "company": existing.get("company") or "Unknown Company",
                    "score": round(existing.get("relevance_score", 0), 1),
                    "url": job_url,
                    "is_scholarship": is_scholarship or existing.get("job_type") == "Scholarship",
                    "is_liked": existing.get("status") == "liked",
                    "is_applied": existing.get("is_applied") == 1
                })
                continue

            try:
                job_dict = scrape_job_from_url(url=job_url, scraper_type="auto", is_scholarship=is_scholarship)
                if is_liked:
                    job_dict["status"] = "liked"
                if is_applied:
                    job_dict["is_applied"] = 1

                # 2. Check if job_id already in DB (different URL pointing to same job)
                if job_dict.get("job_id"):
                    existing_by_id = get_job_by_id(job_dict["job_id"])
                    if existing_by_id:
                        if is_liked or is_applied or is_scholarship:
                            upd = dict(existing_by_id)
                            if is_scholarship: upd["job_type"] = "Scholarship"
                            if is_liked: upd["status"] = "liked"
                            if is_applied: upd["is_applied"] = 1
                            saved_job, _ = save_or_update_job(upd, force_pending=False)
                            results.append({
                                "status": "updated",
                                "title": saved_job.get("title") or "Existing Job",
                                "company": saved_job.get("company") or "Unknown Company",
                                "score": round(saved_job.get("relevance_score", 0), 1),
                                "url": job_url,
                                "is_scholarship": saved_job.get("job_type") == "Scholarship",
                                "is_liked": saved_job.get("status") == "liked",
                                "is_applied": saved_job.get("is_applied") == 1
                            })
                            continue

                        logger.info(f"Telegram bot skipped duplicate job_id: {job_dict['job_id']}")
                        results.append({
                            "status": "duplicate",
                            "title": existing_by_id.get("title") or "Existing Job",
                            "company": existing_by_id.get("company") or "Unknown Company",
                            "score": round(existing_by_id.get("relevance_score", 0), 1),
                            "url": job_url,
                            "is_scholarship": is_scholarship or existing_by_id.get("job_type") == "Scholarship",
                            "is_liked": existing_by_id.get("status") == "liked",
                            "is_applied": existing_by_id.get("is_applied") == 1
                        })
                        continue

                score = round(job_dict.get("relevance_score", 0), 1)
                title = job_dict.get("title") or "Unknown Title"
                company = job_dict.get("company") or "Unknown Company"
                location = job_dict.get("location") or "Not Specified"

                saved_job, is_new = save_or_update_job(job_dict, force_pending=force_pending)

                title = saved_job.get("title") or "Unknown Title"
                company = saved_job.get("company") or "Unknown Company"
                location = saved_job.get("location") or "Not Specified"
                score = round(saved_job.get("relevance_score", 0), 1)

                if is_new:
                    record_new_telegram_job(title)
                    results.append({
                        "status": "added",
                        "title": title,
                        "company": company,
                        "location": location,
                        "score": score,
                        "url": job_url,
                        "is_scholarship": is_scholarship or saved_job.get("job_type") == "Scholarship",
                        "is_liked": saved_job.get("status") == "liked",
                        "is_applied": saved_job.get("is_applied") == 1
                    })
                else:
                    results.append({
                        "status": "duplicate",
                        "title": title,
                        "company": company,
                        "score": score,
                        "url": job_url,
                        "is_scholarship": is_scholarship or saved_job.get("job_type") == "Scholarship",
                        "is_liked": saved_job.get("status") == "liked",
                        "is_applied": saved_job.get("is_applied") == 1
                    })
            except Exception as e:
                logger.error(f"Failed to scrape job from URL '{job_url}': {e}", exc_info=True)
                results.append({
                    "status": "error",
                    "url": job_url,
                    "error": str(e)
                })
    else:
        # No URL found: Treat entire message as raw job description text
        if len(text) < 15:
            send_message(
                bot_token, chat_id,
                "ℹ️ Please share a job link (e.g. from LinkedIn or Wuzzuf) or paste a complete job description text."
            )
            return []

        logger.info(f"Telegram bot processing raw job text (scholarship={is_scholarship}, liked={is_liked}, applied={is_applied})")
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
                        if is_scholarship: upd["job_type"] = "Scholarship"
                        if is_liked: upd["status"] = "liked"
                        if is_applied: upd["is_applied"] = 1
                        saved_job, _ = save_or_update_job(upd, force_pending=False)
                        results.append({
                            "status": "updated",
                            "title": saved_job.get("title") or "Existing Job",
                            "company": saved_job.get("company") or "Unknown Company",
                            "score": round(saved_job.get("relevance_score", 0), 1),
                            "is_scholarship": saved_job.get("job_type") == "Scholarship",
                            "is_liked": saved_job.get("status") == "liked",
                            "is_applied": saved_job.get("is_applied") == 1
                        })
                        if send_reply:
                            send_summary_reply(bot_token, chat_id, results)
                        return results

                    logger.info(f"Telegram bot skipped duplicate raw text job: {existing.get('title')}")
                    results.append({
                        "status": "duplicate",
                        "title": existing.get("title") or "Existing Job",
                        "company": existing.get("company") or "Unknown Company",
                        "score": round(existing.get("relevance_score", 0), 1),
                        "is_scholarship": is_scholarship or existing.get("job_type") == "Scholarship",
                        "is_liked": existing.get("status") == "liked",
                        "is_applied": existing.get("is_applied") == 1
                    })
                    if send_reply:
                        send_summary_reply(bot_token, chat_id, results)
                    return results

            score = round(job_dict.get("relevance_score", 0), 1)
            title = job_dict.get("title") or "Extracted Role"
            company = job_dict.get("company") or "Extracted Company"
            location = job_dict.get("location") or "Not Specified"

            # If job scores 0 or less and is neither Liked, Applied, nor a Scholarship, prune it immediately
            if not is_liked and not is_applied and not is_scholarship and score <= 0:
                delete_job_by_id(job_dict.get("job_id"))
                results.append({
                    "status": "pruned",
                    "title": title,
                    "company": company,
                    "location": location,
                    "score": score,
                    "is_scholarship": False,
                    "is_liked": False,
                    "is_applied": False
                })
                if send_reply:
                    send_summary_reply(bot_token, chat_id, results)
                return results

            saved_job, is_new = save_or_update_job(job_dict, force_pending=force_pending)

            title = saved_job.get("title") or "Extracted Role"
            company = saved_job.get("company") or "Extracted Company"
            location = saved_job.get("location") or "Not Specified"
            score = round(saved_job.get("relevance_score", 0), 1)

            if is_new:
                record_new_telegram_job(title)
                results.append({
                    "status": "added",
                    "title": title,
                    "company": company,
                    "location": location,
                    "score": score,
                    "is_scholarship": is_scholarship or saved_job.get("job_type") == "Scholarship",
                    "is_liked": saved_job.get("status") == "liked",
                    "is_applied": saved_job.get("is_applied") == 1
                })
            else:
                results.append({
                    "status": "duplicate",
                    "title": title,
                    "company": company,
                    "score": score,
                    "is_scholarship": is_scholarship or saved_job.get("job_type") == "Scholarship",
                    "is_liked": saved_job.get("status") == "liked",
                    "is_applied": saved_job.get("is_applied") == 1
                })
        except Exception as e:
            logger.error(f"Failed to parse raw job text: {e}", exc_info=True)
            results.append({
                "status": "error",
                "error": str(e)
            })

    if send_reply and results:
        send_summary_reply(bot_token, chat_id, results)

    return results


def poll_updates(bot_token: str, allowed_chat_id: Optional[str] = None, stop_event: Optional[threading.Event] = None) -> None:
    """
    Main long-polling loop for Telegram updates:
    - Automatically retrieves queued messages received while the app was closed.
    - Accurately tracks last_update_id in telegram_state.json so each message is processed exactly once.
    - Consolidates batch replies so all queued messages receive ONE grouped summary reply.
    - Stops cleanly when stop_event is set.
    """
    state = get_state()
    last_update_id = state.get("last_update_id", 0)

    logger.info(f"Telegram Bot polling started. Starting at last_update_id={last_update_id}")

    session = requests.Session()
    retry_delay = 2

    while stop_event is None or not stop_event.is_set():
        params = {
            "timeout": 15,
        }
        if last_update_id > 0:
            params["offset"] = last_update_id + 1

        url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
        try:
            resp = session.get(url, params=params, timeout=25)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    updates: List[Dict[str, Any]] = data.get("result", [])
                    retry_delay = 2  # reset delay on success

                    batch_results: List[Dict[str, Any]] = []
                    target_chat_id: Optional[str] = None
                    is_batch = len(updates) > 1

                    for update in updates:
                        if stop_event and stop_event.is_set():
                            break

                        u_id = update.get("update_id", 0)
                        if u_id <= last_update_id:
                            continue

                        # Process standard message or channel/forwarded post
                        msg = update.get("message") or update.get("channel_post")
                        if msg:
                            chat = msg.get("chat", {})
                            c_id = str(chat.get("id", ""))
                            if c_id:
                                target_chat_id = c_id
                            try:
                                # If batch (multiple queued), defer reply until all updates are processed
                                msg_results = process_message(
                                    bot_token, msg, allowed_chat_id, send_reply=(not is_batch)
                                )
                                if is_batch and msg_results:
                                    batch_results.extend(msg_results)
                            except Exception as ex:
                                logger.error(f"Error handling update {u_id}: {ex}", exc_info=True)

                        # Commit offset immediately to disk
                        last_update_id = u_id
                        save_state({"last_update_id": last_update_id})

                    # If multiple queued messages were processed in batch, send ONE consolidated summary
                    if is_batch and batch_results and target_chat_id:
                        send_summary_reply(bot_token, target_chat_id, batch_results)

            elif resp.status_code == 401 or resp.status_code == 404:
                logger.error(f"Telegram Bot Token is invalid (HTTP {resp.status_code}). Polling stopped.")
                break
            else:
                logger.warning(f"Telegram getUpdates returned HTTP {resp.status_code}: {resp.text}")
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 30)

        except requests.RequestException as e:
            if stop_event and stop_event.is_set():
                break
            logger.debug(f"Telegram connection error (will retry): {e}")
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 30)
        except Exception as e:
            logger.error(f"Unexpected error in Telegram polling: {e}", exc_info=True)
            time.sleep(5)

    logger.info("Telegram Bot polling stopped cleanly.")


def start_bot_thread(bot_token: str, allowed_chat_id: Optional[str] = None) -> bool:
    """Starts the Telegram bot long-polling loop in a background daemon thread."""
    global _bot_thread, _stop_event
    if not bot_token:
        return False

    stop_bot_thread()

    _stop_event = threading.Event()
    _bot_thread = threading.Thread(
        target=poll_updates,
        args=(bot_token, allowed_chat_id, _stop_event),
        name="TelegramBotPollingThread",
        daemon=True
    )
    _bot_thread.start()
    return True


def stop_bot_thread() -> None:
    """Signals the bot thread to stop and waits up to 2 seconds."""
    global _bot_thread, _stop_event
    if _bot_thread and _bot_thread.is_alive():
        _stop_event.set()
        _bot_thread.join(timeout=2.0)
    _bot_thread = None


def is_bot_running() -> bool:
    """Returns True if the background polling thread is currently alive."""
    return bool(_bot_thread and _bot_thread.is_alive())


def get_latest_chat_id_from_telegram(bot_token: str) -> Optional[Dict[str, Any]]:
    """
    Inspects recent updates or recorded state to find the latest chat_id that messaged the bot.
    Used by the dashboard to auto-detect user's chat_id when setting up.
    """
    global _last_seen_chat
    if _last_seen_chat and _last_seen_chat.get("chat_id"):
        return _last_seen_chat

    state = get_state()
    saved = state.get("last_seen_chat")
    if saved and saved.get("chat_id"):
        return saved

    if bot_token:
        url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
        try:
            resp = requests.get(url, params={"limit": 10, "timeout": 0}, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    updates = data.get("result", [])
                    for u in reversed(updates):
                        msg = u.get("message") or u.get("channel_post")
                        if msg and "chat" in msg:
                            chat_info = {
                                "chat_id": str(msg["chat"]["id"]),
                                "username": msg.get("from", {}).get("username") or msg.get("from", {}).get("first_name", "User"),
                                "text": msg.get("text", "")
                            }
                            _last_seen_chat = chat_info
                            state["last_seen_chat"] = chat_info
                            save_state(state)
                            return chat_info
        except Exception as e:
            logger.error(f"Failed to auto-detect chat_id: {e}")
    return None


def sync_queued_telegram_jobs(bot_token: Optional[str] = None, allowed_chat_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Performs a one-shot batch synchronization with Telegram:
    - Only runs when called (on app launch or GUI reload), NOT as a continuous loop.
    - Retrieves all unread updates from Telegram API in one shot.
    - Processes each message (links vs raw text, skipping duplicates without rescore/re-add).
    - If any jobs were processed, sends ONE consolidated summary message to Telegram (HTML mode).
    - Accurately tracks last_update_id so each message is processed only once.
    - Returns summary dict: {"count": added_count, "jobs": added_job_titles, "duplicates": dup_count}.
    """
    if not bot_token:
        try:
            from core import config as app_config
            bot_token = getattr(app_config, "TELEGRAM_BOT_TOKEN", None) or ""
            if not allowed_chat_id:
                allowed_chat_id = getattr(app_config, "TELEGRAM_CHAT_ID", None) or ""
        except Exception:
            pass

    if not bot_token:
        return {"count": 0, "jobs": [], "duplicates": 0, "status": "not_configured"}

    state = get_state()
    last_update_id = state.get("last_update_id", 0)

    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    all_updates: List[Dict[str, Any]] = []

    # Fetch queued updates (timeout=0 for instant return)
    # Loop to pull all backlogged updates up to 500 messages
    for _ in range(5):
        params: Dict[str, Any] = {"limit": 100, "timeout": 0}
        if last_update_id > 0:
            params["offset"] = last_update_id + 1

        try:
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code != 200:
                logger.warning(f"Telegram getUpdates returned HTTP {resp.status_code}: {resp.text}")
                break
            data = resp.json()
            if not data.get("ok"):
                logger.warning(f"Telegram getUpdates returned error: {data.get('description')}")
                break
            updates: List[Dict[str, Any]] = data.get("result", [])
            if not updates:
                break
            all_updates.extend(updates)
            last_update_id = updates[-1].get("update_id", last_update_id)
            if len(updates) < 100:
                break
        except Exception as e:
            logger.error(f"Error fetching Telegram updates during sync: {e}")
            break

    if not all_updates:
        return {"count": 0, "jobs": [], "duplicates": 0, "status": "no_updates"}

    logger.info(f"Syncing {len(all_updates)} queued Telegram update(s)...")

    batch_results: List[Dict[str, Any]] = []
    target_chat_id: Optional[str] = allowed_chat_id
    highest_update_id = state.get("last_update_id", 0)

    for update in all_updates:
        u_id = update.get("update_id", 0)
        if u_id > highest_update_id:
            highest_update_id = u_id

        msg = update.get("message") or update.get("channel_post")
        if msg:
            chat = msg.get("chat", {})
            c_id = str(chat.get("id", ""))
            if c_id:
                target_chat_id = c_id
            try:
                # Always defer reply so all updates in this sync receive ONE consolidated summary
                msg_results = process_message(
                    bot_token, msg, allowed_chat_id, send_reply=False
                )
                if msg_results:
                    batch_results.extend(msg_results)
            except Exception as ex:
                logger.error(f"Error processing Telegram update {u_id}: {ex}", exc_info=True)

    # Save highest processed update_id to disk
    state["last_update_id"] = highest_update_id
    save_state(state)

    # Send ONE consolidated summary to Telegram if jobs were processed
    if batch_results and target_chat_id:
        send_summary_reply(bot_token, target_chat_id, batch_results)

    added_titles = [r["title"] for r in batch_results if r.get("status") == "added"]
    dup_count = sum(1 for r in batch_results if r.get("status") == "duplicate")

    logger.info(f"Telegram sync complete: {len(added_titles)} added, {dup_count} duplicate(s).")
    return {
        "count": len(added_titles),
        "jobs": added_titles,
        "duplicates": dup_count,
        "status": "success"
    }
