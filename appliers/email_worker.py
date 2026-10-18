import os
import time
import json
import random
import logging
import sqlite3
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.header import Header
from typing import Dict, Any, Optional
from datetime import datetime

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, '.env'))

from core.database import DB_PATH, record_job_applied
from core.applicant_profile import load_profile, get_resume_for_role
from core.telegram_bot import notify_telegram_candidate
from core.quota_manager import (
    AUTOPILOT_STATE_FILE,
    DailyQuotaManager,
    get_autopilot_state,
    save_autopilot_state,
    log_autopilot_activity,
)
from appliers.email_generator import generate_email_draft

logger = logging.getLogger(__name__)


def send_smtp_email(
    smtp_host: str,
    smtp_port: int,
    sender_email: str,
    sender_password: str,
    recipient_email: str,
    subject: str,
    body: str,
    cv_path: Optional[str] = None
) -> bool:
    """Sends an application email via direct SMTP with attached CV PDF."""
    clean_password = (sender_password or "").replace(" ", "").strip()
    msg = MIMEMultipart()
    msg["From"] = sender_email
    msg["To"] = recipient_email
    clean_subject = (subject or "").replace("\r", " ").replace("\n", " ").strip() or "Job Application"
    try:
        clean_subject.encode("ascii")
        msg["Subject"] = clean_subject
    except UnicodeEncodeError:
        msg["Subject"] = Header(clean_subject, "utf-8")
    from core.email_signature import format_email_body_html

    msg_alt = MIMEMultipart("alternative")
    msg_alt.attach(MIMEText(body, "plain", "utf-8"))
    html_content = format_email_body_html(body, append_signature=True)
    msg_alt.attach(MIMEText(html_content, "html", "utf-8"))
    msg.attach(msg_alt)

    if cv_path and os.path.exists(cv_path):
        try:
            with open(cv_path, "rb") as f:
                part = MIMEApplication(f.read(), Name=os.path.basename(cv_path))
            part["Content-Disposition"] = f'attachment; filename="{os.path.basename(cv_path)}"'
            msg.attach(part)
        except Exception as e:
            logger.error(f"Failed to attach CV to SMTP message: {e}")

    try:
        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=25) as server:
                server.login(sender_email, clean_password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=25) as server:
                server.starttls()
                server.login(sender_email, clean_password)
                server.send_message(msg)
        return True
    except Exception as e:
        logger.error(f"SMTP send failed: {e}")
        return False



def run_email_autopilot_batch(
    force: bool = False,
    dry_run: bool = False,
    batch_limit: Optional[int] = None
) -> Dict[str, Any]:
    """
    Executes an autonomous batch of email applications:
    1. Checks daily quota & rate limiters.
    2. Queries highest relevance unapplied email jobs.
    3. Generates tailored cold email drafts & subject hints.
    4. Automatically attaches role CV PDF from configuration.
    5. Dispatches via direct SMTP.
    6. Updates database records and sends Telegram notification.
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
    if not channels_enabled.get("email", True) and not force:
        return {
            "status": "skipped",
            "message": "Email channel is disabled in auto-apply settings.",
            "processed_count": 0
        }

    state = get_autopilot_state()
    max_runs_per_day = settings.get("max_runs_per_day", 5)
    batch_size = batch_limit or settings.get("batch_size_per_run", 3)
    min_score = settings.get("min_relevance_score", 70)

    # Rate Limiter check
    if state["daily_runs_count"] >= max_runs_per_day and not force:
        msg = f"Daily run limit reached ({state['daily_runs_count']}/{max_runs_per_day} runs today). Pausing until tomorrow."
        log_autopilot_activity(msg, state)
        save_autopilot_state(state)
        return {
            "status": "rate_limited",
            "message": msg,
            "processed_count": 0
        }

    # Query unapplied email jobs
    if not os.path.exists(DB_PATH):
        return {"status": "error", "message": "Database not found."}

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM jobs
        WHERE is_applied = 0
          AND apply_type = 'email'
          AND relevance_score >= ?
        ORDER BY relevance_score DESC
        LIMIT ?
    """, (min_score, batch_size))
    candidate_jobs = [dict(r) for r in cursor.fetchall()]
    conn.close()

    if not candidate_jobs:
        msg = f"No eligible unapplied email jobs found with relevance score >= {min_score}."
        log_autopilot_activity(msg, state)
        save_autopilot_state(state)
        return {
            "status": "no_jobs",
            "message": msg,
            "processed_count": 0
        }

    log_autopilot_activity(f"Starting Email Auto-Pilot batch: found {len(candidate_jobs)} target jobs.", state)

    smtp_host = settings.get("smtp_host", "smtp.gmail.com")
    smtp_port = int(settings.get("smtp_port", 465))
    smtp_email = settings.get("smtp_email", "")
    smtp_password = settings.get("smtp_app_password", "")
    use_smtp = bool(smtp_email and smtp_password)

    processed_jobs = []
    success_count = 0

    for idx, job in enumerate(candidate_jobs):
        job_id = job.get("job_id")
        title = job.get("title", "")
        company = job.get("company", "")
        score = job.get("relevance_score", 0)

        # Parse payload
        raw_payload = job.get("apply_payload", {})
        payload = json.loads(raw_payload) if isinstance(raw_payload, str) else (raw_payload or {})
        recipient_email = payload.get("recipient_email") or ""

        if not recipient_email:
            log_autopilot_activity(f"Skipping {title} at {company}: No recipient email extracted.", state)
            continue

        log_autopilot_activity(f"[{idx+1}/{len(candidate_jobs)}] Processing '{title}' at {company} (Score: {score})...", state)

        # Generate draft & resolve role CV
        draft_info = generate_email_draft(job_id=job_id)
        if draft_info.get("status") != "success":
            err_msg = draft_info.get("message", "AI draft generation unavailable")
            log_autopilot_activity(
                f"Discarding email application for '{title}' at {company}: {err_msg}",
                state
            )
            processed_jobs.append({
                "job_id": job_id,
                "title": title,
                "company": company,
                "status": "discarded",
                "message": err_msg
            })
            continue
        cand_name = profile.get("personal_info", {}).get("full_name", "").strip()
        default_subj = f"Application: {title} – {cand_name}" if cand_name else f"Application: {title}"
        subject = (draft_info.get("subject") or "").strip() or default_subj
        body = draft_info.get("body", "")
        cv_path = draft_info.get("cv_path") or get_resume_for_role(title)
        cv_name = os.path.basename(cv_path) if cv_path else "Resume.pdf"

        if dry_run:
            log_autopilot_activity(f"[Dry Run] Would send email to {recipient_email} with CV {cv_name}.", state)
            success_count += 1
            processed_jobs.append({"job_id": job_id, "title": title, "status": "dry_run_success"})
            continue

        send_success = False
        delivery_method = "simulation"

        # Direct SMTP delivery
        if use_smtp:
            send_success = send_smtp_email(
                smtp_host=smtp_host,
                smtp_port=smtp_port,
                sender_email=smtp_email,
                sender_password=smtp_password,
                recipient_email=recipient_email,
                subject=subject,
                body=body,
                cv_path=cv_path
            )
            delivery_method = "smtp"
        else:
            logger.error("SMTP credentials (email or app password) not configured.")
            log_autopilot_activity(
                f"Skipping {title} at {company}: SMTP credentials missing. Configure App Password in Settings.",
                state
            )
            send_success = False
            delivery_method = "failed_no_credentials"

        if send_success:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            payload["sent_email"] = {
                "recipient": recipient_email,
                "subject": subject,
                "delivery_method": delivery_method,
                "timestamp": now_str,
                "cv_attached": cv_name
            }

            # Update DB record
            record_job_applied(job_id=job_id, channel="sent_email", extra_payload=payload["sent_email"])

            success_count += 1
            state["emails_sent_today"] += 1
            state["total_applied_all_time"] += 1

            log_autopilot_activity(f"✓ Successfully dispatched email to {recipient_email} for '{title}'!", state)

            processed_jobs.append({
                "job_id": job_id,
                "title": title,
                "company": company,
                "recipient": recipient_email,
                "status": "applied",
                "method": delivery_method
            })

            # Add throttling jitter delay between sends (5–12s) to protect sender domain reputation
            if idx < len(candidate_jobs) - 1:
                jitter = random.uniform(5.0, 10.0)
                log_autopilot_activity(f"Throttling jitter delay: waiting {jitter:.1f}s before next send...", state)
                time.sleep(jitter)
        else:
            log_autopilot_activity(f"Failed to send email to {recipient_email} for '{title}'.", state)
            notify_telegram_candidate(f"⚠️ Auto-Pilot Failed: Could not send email for '{title}' at {company} ({recipient_email}).")
            processed_jobs.append({
                "job_id": job_id,
                "title": title,
                "status": "failed"
            })

    state["daily_runs_count"] += 1
    save_autopilot_state(state)

    summary_msg = f"Email Auto-Pilot batch complete: {success_count}/{len(candidate_jobs)} applications sent."
    log_autopilot_activity(summary_msg, state)

    return {
        "status": "success",
        "message": summary_msg,
        "processed_count": success_count,
        "total_targets": len(candidate_jobs),
        "results": processed_jobs,
        "state": state
    }
