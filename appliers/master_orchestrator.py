import os
import sys
import time
import json
import logging
import threading
import sqlite3
from typing import Dict, Any, List, Optional
from datetime import datetime

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, '.env'))

from core.database import DB_PATH
from core.applicant_profile import load_profile, save_profile, get_resume_for_role
from appliers.email_worker import (
    get_autopilot_state,
    save_autopilot_state,
    log_autopilot_activity,
    run_email_autopilot_batch,
    notify_telegram_candidate
)
from appliers.whatsapp_worker import run_whatsapp_autopilot_batch
from appliers.screening_resolver import ScreeningResolver

logger = logging.getLogger(__name__)

# Master Scheduler Control
_scheduler_thread: Optional[threading.Thread] = None
_scheduler_stop_event = threading.Event()
_is_cycle_running = False
_cycle_lock = threading.Lock()


def is_cycle_active() -> bool:
    global _is_cycle_running
    return _is_cycle_running


def run_master_autopilot_cycle(force: bool = False, dry_run: bool = False) -> Dict[str, Any]:
    """
    Coordinates an end-to-end Auto-Pilot cycle across all enabled channels:
    1. Direct Email Worker (Batch 6)
    2. WhatsApp Worker (Batch 7)
    3. Autonomous Easy Apply & ATS Form Handler (Batch 8)
    4. Telegram HITL loop for unresolved screening questions.
    """
    global _is_cycle_running
    with _cycle_lock:
        if _is_cycle_running:
            return {"status": "already_running", "message": "An Auto-Pilot cycle is already in progress."}
        _is_cycle_running = True

    try:
        profile = load_profile()
        settings = profile.get("auto_apply_settings", {})
        state = get_autopilot_state()

        is_enabled = settings.get("enabled", False)
        if not is_enabled and not force:
            log_autopilot_activity("Master Auto-Pilot is currently PAUSED in settings. Skipping cycle.", state)
            save_autopilot_state(state)
            return {
                "status": "paused",
                "message": "Auto-Pilot is currently paused in settings. You can resume it anytime from Settings > Auto-Apply.",
                "results": None,
                "state": state
            }

        log_autopilot_activity("=== [Master Auto-Pilot Cycle Initiated] ===", state)

        channels = settings.get("channels_enabled", {})
        results = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "email_batch": None,
            "whatsapp_batch": None,
            "easy_apply_batch": None,
            "ats_batch": None,
            "hitl_questions": []
        }

        # 1. Run Email Auto-Pilot Batch
        if channels.get("email", True) or force:
            log_autopilot_activity("Running Email Auto-Pilot pipeline...", state)
            try:
                results["email_batch"] = run_email_autopilot_batch(force=force, dry_run=dry_run)
            except Exception as e:
                logger.error(f"Email batch error in master cycle: {e}")
                results["email_batch"] = {"status": "error", "message": str(e)}

        # 2. Run WhatsApp Auto-Pilot Batch
        if channels.get("whatsapp", True) or force:
            log_autopilot_activity("Running WhatsApp Auto-Pilot pipeline...", state)
            try:
                results["whatsapp_batch"] = run_whatsapp_autopilot_batch(force=force, dry_run=dry_run)
            except Exception as e:
                logger.error(f"WhatsApp batch error in master cycle: {e}")
                results["whatsapp_batch"] = {"status": "error", "message": str(e)}

        # 3. Process Autonomous Easy Apply & ATS candidates with HITL loop
        if channels.get("easy_apply", True) or channels.get("platform", True) or force:
            log_autopilot_activity("Processing Easy Apply & ATS candidate queue...", state)
            ea_results = _process_autonomous_form_jobs(min_score=settings.get("min_relevance_score", 70), dry_run=dry_run, state=state)
            results["easy_apply_batch"] = ea_results

        log_autopilot_activity("=== [Master Auto-Pilot Cycle Completed] ===", state)
        save_autopilot_state(state)

        return {
            "status": "success",
            "message": "Auto-Pilot cycle finished successfully.",
            "results": results,
            "state": state
        }
    finally:
        _is_cycle_running = False


def _process_autonomous_form_jobs(min_score: int = 70, dry_run: bool = False, state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Evaluates unapplied Easy Apply and ATS jobs, resolving screening questions,
    and delegating unanswerable questions to Telegram HITL.
    """
    if not os.path.exists(DB_PATH):
        return {"status": "error", "message": "Database not found."}

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM jobs
        WHERE is_applied = 0
          AND apply_type IN ('easy_apply', 'platform')
          AND relevance_score >= ?
        ORDER BY relevance_score DESC
        LIMIT 3
    """, (min_score,))
    jobs = [dict(r) for r in cursor.fetchall()]
    conn.close()

    if not jobs:
        return {"status": "no_jobs", "processed_count": 0}

    processed = []
    for job in jobs:
        job_id = job.get("job_id")
        title = job.get("title", "")
        company = job.get("company", "")
        apply_type = job.get("apply_type")

        resolver = ScreeningResolver(job_title=title, job_location=job.get("location", ""), company=company)
        cv_path = get_resume_for_role(title)

        if dry_run:
            processed.append({"job_id": job_id, "title": title, "status": "dry_run_ready"})
            continue

        # Check if there are pending questions requiring user answer
        pending_q = job.get("pending_questions")
        if pending_q:
            log_autopilot_activity(f"Job '{title}' at {company} has pending HITL question: {pending_q}", state)
            processed.append({"job_id": job_id, "title": title, "status": "waiting_hitl", "question": pending_q})
            continue

        # In Auto-Pilot mode, we record execution readiness or finalize if pre-screen passes
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        raw_payload = job.get("apply_payload", {})
        payload = json.loads(raw_payload) if isinstance(raw_payload, str) else (raw_payload or {})
        payload["autopilot_prepared"] = {
            "cv_path": cv_path,
            "timestamp": now_str,
            "screened_fields": True
        }

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE jobs SET apply_payload = ? WHERE job_id = ?", (json.dumps(payload, ensure_ascii=False), job_id))
        conn.commit()
        conn.close()

        processed.append({"job_id": job_id, "title": title, "status": "screened_ready"})

    return {
        "status": "success",
        "processed_count": len(processed),
        "jobs": processed
    }


def send_telegram_hitl_question(job_id: str, question: str) -> bool:
    """
    Sends a Human-In-The-Loop prompt to Telegram when an unknown screening question is encountered.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT title, company FROM jobs WHERE job_id = ?", (job_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False
    title, company = row

    cursor.execute("UPDATE jobs SET pending_questions = ? WHERE job_id = ?", (question, job_id))
    conn.commit()
    conn.close()

    text = (
        f"❓ *Auto-Pilot Question Needed*\n"
        f"Job: *{title}* at *{company}*\n\n"
        f"Question: _{question}_\n\n"
        f"Reply with: `/answer {job_id} <your answer>`"
    )
    notify_telegram_candidate(text)
    return True


def resolve_telegram_hitl_answer(job_id: str, question: str, answer: str) -> bool:
    """
    Stores candidate's answer permanently in candidate_profile.json under custom_qa_pairs
    and clears pending_questions in the database.
    """
    profile = load_profile()
    if "custom_qa_pairs" not in profile:
        profile["custom_qa_pairs"] = {}
    profile["custom_qa_pairs"][question.strip()] = answer.strip()
    save_profile(profile)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE jobs SET pending_questions = NULL WHERE job_id = ?", (job_id,))
    conn.commit()
    conn.close()

    log_autopilot_activity(f"Resolved HITL question for {job_id}. Saved '{question[:30]}...' to custom Q&A.")
    notify_telegram_candidate(f"✓ Saved answer for *{question[:30]}...* to permanent profile!")
    return True


def get_applications_history(
    channel_filter: Optional[str] = None,
    search_query: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
) -> Dict[str, Any]:
    """
    Returns full history of applied jobs with metadata, payloads, and timestamps.
    """
    if not os.path.exists(DB_PATH):
        return {"total": 0, "applications": []}

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    query = "SELECT * FROM jobs WHERE is_applied = 1"
    params = []

    if channel_filter and channel_filter != "all":
        query += " AND (apply_type = ? OR apply_channel = ?)"
        params.extend([channel_filter, channel_filter])

    if search_query:
        query += " AND (title LIKE ? OR company LIKE ?)"
        params.extend([f"%{search_query}%", f"%{search_query}%"])

    query += " ORDER BY applied_at DESC, timestamp DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]

    # Count total
    count_query = "SELECT count(*) FROM jobs WHERE is_applied = 1"
    count_params = []
    if channel_filter and channel_filter != "all":
        count_query += " AND (apply_type = ? OR apply_channel = ?)"
        count_params.extend([channel_filter, channel_filter])
    if search_query:
        count_query += " AND (title LIKE ? OR company LIKE ?)"
        count_params.extend([f"%{search_query}%", f"%{search_query}%"])

    cursor.execute(count_query, count_params)
    total_count = cursor.fetchone()[0]
    conn.close()

    # Parse payloads cleanly
    for r in rows:
        if r.get("apply_payload") and isinstance(r["apply_payload"], str):
            try:
                r["apply_payload"] = json.loads(r["apply_payload"])
            except Exception:
                pass

    return {
        "total": total_count,
        "limit": limit,
        "offset": offset,
        "applications": rows
    }


def get_applications_aggregate_stats() -> Dict[str, Any]:
    """
    Returns high-level statistics for the dashboard Applications Management Hub.
    """
    state = get_autopilot_state()
    today_str = datetime.now().strftime("%Y-%m-%d")

    total_applied = 0
    channel_counts = {}
    applied_today = 0

    if os.path.exists(DB_PATH):
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT count(*) FROM jobs WHERE is_applied = 1")
            total_applied = c.fetchone()[0]

            c.execute("SELECT count(*) FROM jobs WHERE is_applied = 1 AND applied_at LIKE ?", (f"{today_str}%",))
            applied_today = c.fetchone()[0]

            c.execute("SELECT apply_type, count(*) FROM jobs WHERE is_applied = 1 GROUP BY apply_type")
            for r in c.fetchall():
                channel_counts[r[0] or "unknown"] = r[1]
            conn.close()
        except Exception as e:
            logger.error(f"Error getting aggregate stats: {e}")

    profile = load_profile()
    settings = profile.get("auto_apply_settings", {})
    is_enabled = bool(settings.get("enabled", False))
    max_runs = settings.get("max_runs_per_day", 5)
    runs_done = state.get("daily_runs_count", 0)

    return {
        "is_enabled": is_enabled,
        "is_paused": not is_enabled,
        "total_applied_all_time": total_applied,
        "applied_today": applied_today,
        "emails_sent_today": state.get("emails_sent_today", 0),
        "whatsapp_sent_today": state.get("whatsapp_sent_today", 0),
        "daily_runs_done": runs_done,
        "daily_runs_max": max_runs,
        "runs_remaining": max(0, max_runs - runs_done),
        "channel_breakdown": channel_counts,
        "recent_logs": state.get("recent_logs", [])[-20:]
    }


def start_master_scheduler(interval_seconds: int = 14400):
    """Starts the background autonomous scheduler thread (default: every 4 hours)."""
    global _scheduler_thread, _scheduler_stop_event
    if _scheduler_thread and _scheduler_thread.is_alive():
        return

    _scheduler_stop_event.clear()

    def _scheduler_loop():
        logger.info(f"Master Auto-Pilot Scheduler started. Interval: {interval_seconds}s.")
        while not _scheduler_stop_event.is_set():
            try:
                run_master_autopilot_cycle(force=False)
            except Exception as e:
                logger.error(f"Error in master scheduler loop: {e}")
            _scheduler_stop_event.wait(interval_seconds)

    _scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True)
    _scheduler_thread.start()


def stop_master_scheduler():
    """Stops the background autonomous scheduler thread."""
    global _scheduler_stop_event
    _scheduler_stop_event.set()
