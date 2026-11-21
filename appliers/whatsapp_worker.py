import os
import time
import json
import random
import logging
import sqlite3
import urllib.parse
from typing import Dict, Any, Optional
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, '.env'))
except ImportError:
    pass

from core.database import (
    DB_PATH,
    record_job_applied,
    get_autopilot_applied_tracker,
    is_job_eligible_for_autopilot,
    register_autopilot_applied,
)
from core.applicant_profile import load_profile, get_resume_for_role
from appliers.whatsapp_copilot import generate_whatsapp_pitch, normalize_phone_number
from core.quota_manager import (
    get_autopilot_state,
    save_autopilot_state,
    log_autopilot_activity,
)
from core.whatsapp_bot import notify_whatsapp_candidate
from core.config import (
    get_edge_binary_path,
    get_browser_user_data_dir,
    get_browser_launch_kwargs,
    get_clean_browser_page,
)

logger = logging.getLogger(__name__)

MAX_WHATSAPP_DAILY_CAP = 5


def run_whatsapp_autopilot_batch(
    force: bool = False,
    dry_run: bool = False,
    batch_limit: Optional[int] = None,
    headed: bool = False
) -> Dict[str, Any]:
    """
    Executes an autonomous batch of WhatsApp applications using Playwright Web automation:
    1. Enforces strict anti-ban daily limits and human-like pacing.
    2. Queries highest relevance unapplied WhatsApp jobs.
    3. Formulates strictly professional English AI recruiter pitch.
    4. Attaches matched role CV PDF from configuration.
    5. Dispatches application and tracks completion in database.
    """
    profile = load_profile()
    settings = profile.get("auto_apply_settings", {})
    is_enabled = settings.get("enabled", False)

    if not is_enabled and not force:
        return {
            "status": "skipped",
            "message": "Auto-apply is currently disabled in settings.",
            "processed_count": 0
        }

    channels_enabled = settings.get("channels_enabled", {})
    if not channels_enabled.get("whatsapp", False):
        return {
            "status": "skipped",
            "message": "WhatsApp channel is disabled in auto-apply settings.",
            "processed_count": 0
        }

    state = get_autopilot_state()
    daily_sent = state.get("whatsapp_sent_today", 0)
    batch_size = batch_limit or min(settings.get("batch_size_per_run", 3), MAX_WHATSAPP_DAILY_CAP - daily_sent)
    min_score = settings.get("min_relevance_score", 70)

    # Strict anti-ban check
    if daily_sent >= MAX_WHATSAPP_DAILY_CAP and not force:
        msg = f"WhatsApp anti-ban daily safety cap reached ({daily_sent}/{MAX_WHATSAPP_DAILY_CAP} sent today). Pausing WhatsApp automation until tomorrow."
        log_autopilot_activity(msg, state)
        save_autopilot_state(state)
        return {
            "status": "rate_limited",
            "message": msg,
            "processed_count": 0
        }

    if batch_size <= 0:
        msg = "Daily WhatsApp allocation exhausted."
        return {"status": "rate_limited", "message": msg, "processed_count": 0}

    # Query unapplied WhatsApp jobs
    if not os.path.exists(DB_PATH):
        return {"status": "error", "message": "Database not found."}

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    tracker = get_autopilot_applied_tracker(conn)
    cursor = conn.cursor()

    fetch_limit = max(batch_size * 5, 20)
    cursor.execute("""
        SELECT * FROM jobs
        WHERE is_applied = 0
          AND (apply_status IS NULL OR apply_status != 'applied')
          AND (status IS NULL OR status IN ('pending', 'liked'))
          AND status NOT IN ('not_related', 'filtered', 'applied')
          AND apply_type = 'whatsapp'
          AND relevance_score > 0
          AND relevance_score >= ?
        ORDER BY relevance_score DESC
        LIMIT ?
    """, (min_score, fetch_limit))
    raw_candidates = [dict(r) for r in cursor.fetchall()]
    conn.close()

    candidate_jobs = []
    for c_job in raw_candidates:
        eligible, reason = is_job_eligible_for_autopilot(
            c_job,
            applied_tracker=tracker,
            min_score=min_score,
            channel="whatsapp",
            channels_enabled=channels_enabled
        )
        if eligible:
            candidate_jobs.append(c_job)
        else:
            log_autopilot_activity(f"Auto-Pilot filter: Excluding '{c_job.get('title')}' at {c_job.get('company')} ({reason}).", state)

    if not candidate_jobs:
        msg = f"No eligible unapplied WhatsApp jobs found with relevance score >= {min_score}."
        log_autopilot_activity(msg, state)
        save_autopilot_state(state)
        return {
            "status": "no_jobs",
            "message": msg,
            "processed_count": 0
        }

    log_autopilot_activity(f"Starting WhatsApp Auto-Pilot batch: found {len(candidate_jobs)} candidates to fulfill quota of {batch_size}.", state)

    processed_jobs = []
    success_count = 0

    # Execute batch
    for idx, job in enumerate(candidate_jobs):
        if success_count >= batch_size:
            break

        job_id = job.get("job_id")
        title = job.get("title", "")
        company = job.get("company", "")
        score = job.get("relevance_score", 0)

        # Authoritative eligibility re-check
        eligible, reason = is_job_eligible_for_autopilot(
            job,
            applied_tracker=tracker,
            min_score=min_score,
            channel="whatsapp",
            channels_enabled=channels_enabled
        )
        if not eligible:
            log_autopilot_activity(f"Skipping '{title}' at {company}: {reason}.", state)
            continue

        raw_payload = job.get("apply_payload", {})
        payload = json.loads(raw_payload) if isinstance(raw_payload, str) else (raw_payload or {})
        raw_phone = payload.get("phone", "")
        if not raw_phone and payload.get("whatsapp_url"):
            import re
            m = re.search(r'(?:wa\.me/|phone=)(\d+)', payload.get("whatsapp_url", ""))
            if m:
                raw_phone = m.group(1)
        phone = normalize_phone_number(raw_phone)

        if not phone:
            log_autopilot_activity(f"Skipping {title} at {company}: No valid phone number resolved.", state)
            continue

        from core.database import _clean_phone
        clean_p = _clean_phone(phone)
        if clean_p and clean_p in tracker.get("applied_phones", set()):
            log_autopilot_activity(f"Skipping '{title}' at {company}: WhatsApp contact '{phone}' was already applied to.", state)
            continue

        log_autopilot_activity(f"[{idx+1}/{len(candidate_jobs)}] Formulating English pitch for '{title}' at {company} (Phone: {phone})...", state)

        # Generate tailored English pitch & role CV
        pitch_data = generate_whatsapp_pitch(job_id=job_id)
        if pitch_data.get("status") != "success":
            err_msg = pitch_data.get("message", "AI pitch generation unavailable")
            log_autopilot_activity(
                f"Postponing WhatsApp application for '{title}' at {company}: {err_msg}",
                state
            )
            processed_jobs.append({
                "job_id": job_id,
                "title": title,
                "company": company,
                "status": "postponed",
                "message": err_msg
            })
            continue

        pitch_text = pitch_data.get("pitch", "")
        cv_path = pitch_data.get("cv_path") or get_resume_for_role(title)
        cv_name = os.path.basename(cv_path) if cv_path else "Resume.pdf"

        if dry_run:
            log_autopilot_activity(f"[Dry Run] Would send WhatsApp message to {phone} with CV {cv_name}.", state)
            register_autopilot_applied(job, tracker, phone=phone)
            success_count += 1
            processed_jobs.append({"job_id": job_id, "title": title, "status": "dry_run_success"})
            if success_count >= batch_size:
                break
            continue

        # Execute automated dispatch via Playwright WhatsApp Web
        send_success = False
        dispatch_method = "playwright_web"

        try:
            send_success = _send_whatsapp_message_via_playwright(
                phone=phone,
                message=pitch_text,
                cv_path=cv_path,
                headed=headed
            )
        except Exception as err:
            logger.error(f"Playwright WhatsApp error: {err}")
            send_success = False
            dispatch_method = "failed"

        if send_success:
            register_autopilot_applied(job, tracker, phone=phone)
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            payload["sent_whatsapp"] = {
                "phone": phone,
                "dispatch_method": dispatch_method,
                "timestamp": now_str,
                "cv_attached": cv_name
            }

            # Update DB record
            record_job_applied(job_id=job_id, channel="sent_whatsapp", extra_payload=payload["sent_whatsapp"])

            success_count += 1
            state["whatsapp_sent_today"] = state.get("whatsapp_sent_today", 0) + 1
            state["total_applied_all_time"] = state.get("total_applied_all_time", 0) + 1

            log_autopilot_activity(f"✓ Successfully sent WhatsApp application to {phone} for '{title}'!", state)

            processed_jobs.append({
                "job_id": job_id,
                "title": title,
                "company": company,
                "phone": phone,
                "status": "applied",
                "method": dispatch_method
            })

            if success_count >= batch_size:
                break

            # Anti-ban safety pacing between chats (15–25s)
            if idx < len(candidate_jobs) - 1:
                delay = random.uniform(15.0, 25.0)
                log_autopilot_activity(f"Anti-ban safety pacing: waiting {delay:.1f}s before next chat...", state)
                time.sleep(delay)
        else:
            log_autopilot_activity(f"Failed to send WhatsApp message to {phone} for '{title}'.", state)
            notify_whatsapp_candidate(f"⚠️ Auto-Pilot Failed: Could not send WhatsApp message for '{title}' at {company} ({phone}).")
            processed_jobs.append({
                "job_id": job_id,
                "title": title,
                "status": "failed"
            })

    state["daily_runs_count"] = state.get("daily_runs_count", 0) + 1
    save_autopilot_state(state)

    summary = f"WhatsApp Auto-Pilot batch complete: {success_count}/{len(candidate_jobs)} sent."
    log_autopilot_activity(summary, state)

    return {
        "status": "success",
        "message": summary,
        "processed_count": success_count,
        "total_targets": len(candidate_jobs),
        "results": processed_jobs,
        "state": state
    }


def _attach_cv_in_whatsapp_web(page, cv_path: str, click_send: bool = True) -> bool:
    """
    Attaches and optionally dispatches a CV document in WhatsApp Web:
    1. Stages CV PDF on clipboard (CF_HDROP) for paste fallback.
    2. Looks for the document file input (accept='*' or non-image) or clicks Attach (+) menu.
    3. Clicks Document menu item to open document file picker.
    4. Falls back to clipboard paste (Ctrl+V) if DOM input was not triggerable.
    5. Waits for the WhatsApp Web Document Preview modal to render.
    6. If click_send=True (Autopilot), clicks the Document Preview Send button.
       If click_send=False (Copilot review), leaves preview open for user review.
    """
    if not cv_path or not os.path.exists(cv_path):
        return False

    # Stage on clipboard so Ctrl+V is ready
    try:
        from appliers.gmail_launcher import copy_file_to_clipboard
        copy_file_to_clipboard(cv_path)
    except Exception:
        pass

    attached = False
    try:
        # Multi-strategy 1: Check existing document file input (exclude media inputs with accept="image/*")
        doc_inputs = page.query_selector_all("input[type='file']:not([accept*='image']):not([accept*='video'])")
        for din in doc_inputs:
            try:
                din.set_input_files(cv_path)
                attached = True
                time.sleep(1.5)
                break
            except Exception:
                continue

        # Multi-strategy 2: Click the attach (+) button to reveal the Document menu item
        if not attached:
            attach_btn = page.query_selector(
                "button[title='Attach'], button[aria-label='Attach'], span[data-icon='plus'], "
                "span[data-icon='attach-menu-plus'], div[title='Attach'], div[aria-label='Attach'], "
                "div[aria-label='Attach menu']"
            )
            if attach_btn:
                try:
                    attach_btn.click()
                    time.sleep(1.0)
                except Exception:
                    pass

                # Look for the Document option
                doc_btn = page.query_selector(
                    "span[data-icon='attach-document'], span[data-icon='document'], "
                    "button[aria-label*='Document'], div[aria-label*='Document'], "
                    "li:has(span[data-icon='attach-document'])"
                )
                if doc_btn:
                    try:
                        with page.expect_file_chooser(timeout=4000) as fc_info:
                            doc_btn.click()
                        file_chooser = fc_info.value
                        file_chooser.set_files(cv_path)
                        attached = True
                        time.sleep(1.5)
                    except Exception:
                        # Re-check file inputs after clicking attach
                        doc_inputs = page.query_selector_all("input[type='file']:not([accept*='image'])")
                        for din in doc_inputs:
                            try:
                                din.set_input_files(cv_path)
                                attached = True
                                time.sleep(1.5)
                                break
                            except Exception:
                                continue

        # Multi-strategy 3: Clipboard paste fallback into chat box
        if not attached:
            try:
                from appliers.gmail_launcher import copy_file_to_clipboard
                if copy_file_to_clipboard(cv_path):
                    chat_box = page.query_selector("div[contenteditable='true']")
                    if chat_box:
                        chat_box.click()
                        time.sleep(0.5)
                        page.keyboard.press("Control+v")
                        time.sleep(2.0)
                        attached = True
            except Exception as e:
                logger.debug(f"Clipboard paste fallback error: {e}")

        # Check for Document Preview modal
        preview_send_btn = None
        try:
            preview_send_btn = page.wait_for_selector(
                "div[aria-label='Send'], button[aria-label='Send'], span[data-icon='send'], "
                "span[data-icon='wds-ic-send-filled'], div[data-icon='send']",
                timeout=10000
            )
        except Exception:
            pass

        if preview_send_btn:
            if click_send:
                preview_send_btn.click()
                time.sleep(3.0)
                logger.info(f"Successfully attached and sent CV: {os.path.basename(cv_path)}")
                return True
            else:
                logger.info(f"Document uploaded to preview modal; awaiting user confirmation: {os.path.basename(cv_path)}")
                return True
        elif attached:
            logger.info(f"CV attached in WhatsApp Web: {os.path.basename(cv_path)}")
            return True
    except Exception as e:
        logger.warning(f"Error attaching CV in WhatsApp Web: {e}")

    return attached


def _send_whatsapp_message_via_playwright(
    phone: str,
    message: str,
    cv_path: Optional[str] = None,
    headed: bool = False
) -> bool:
    """Automates WhatsApp Web message sending with CV attachment."""
    from playwright.sync_api import sync_playwright

    user_data_dir = get_browser_user_data_dir()
    browser_launch_kwargs = get_browser_launch_kwargs()
    try:
        from core.auth_status import sync_profile_storage
        sync_profile_storage(user_data_dir)
    except Exception:
        pass

    encoded_text = urllib.parse.quote(message)
    target_url = f"https://web.whatsapp.com/send?phone={phone}&text={encoded_text}"

    with sync_playwright() as p:
        launch_kwargs = {
            "user_data_dir": user_data_dir,
            "headless": False if headed else True,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-restore-session-state",
                "--disable-session-crashed-bubble",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-features=msEdgeSingleSignOn,msEdgeAutoSignIn,msImplicitSignIn",
            ],
            "ignore_default_args": ["--enable-automation", "--disable-extensions", "--disable-component-update"],
            **browser_launch_kwargs
        }

        context = p.chromium.launch_persistent_context(**launch_kwargs)
        page = get_clean_browser_page(context)

        try:
            page.goto(target_url, timeout=35000, wait_until="domcontentloaded")
            time.sleep(4.0)

            # Check if QR code authentication is required
            qr_code = page.query_selector("canvas[aria-label*='Scan'], div[data-ref]")
            if qr_code:
                logger.warning("WhatsApp Web session requires QR code login. Stopping automated send.")
                context.close()
                return False

            # Wait for chat input or send button
            send_btn = page.wait_for_selector(
                "button[aria-label='Send'], span[data-icon='send'], span[data-icon='wds-ic-send-filled']",
                timeout=20000
            )

            message_sent = False
            if send_btn:
                send_btn.click()
                time.sleep(2.5)
                message_sent = True

            # Attach CV PDF if provided and message was dispatched
            if cv_path and os.path.exists(cv_path):
                _attach_cv_in_whatsapp_web(page, cv_path)

            context.close()
            return message_sent
        except Exception as e:
            logger.error(f"Playwright WhatsApp execution error: {e}")
            context.close()
            return False
