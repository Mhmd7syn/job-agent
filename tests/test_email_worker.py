import os
import json
import sqlite3
import pytest
from unittest.mock import patch

from appliers.email_worker import (
    get_autopilot_state,
    save_autopilot_state,
    run_email_autopilot_batch,
    AUTOPILOT_STATE_FILE
)
from core.database import DB_PATH


def test_autopilot_state_management():
    """Verifies that state initializes and resets daily counters cleanly."""
    state = get_autopilot_state()
    assert "last_run_date" in state
    assert "daily_runs_count" in state
    assert "emails_sent_today" in state
    assert isinstance(state["recent_logs"], list)


def test_email_worker_paused_by_default():
    """Verifies that email worker is paused by default and returns skipped when force=False."""
    res = run_email_autopilot_batch(force=False)
    assert res["status"] == "skipped"
    assert "disabled" in res["message"].lower() or "paused" in res["message"].lower()


def test_rate_limiter_blocks_when_max_reached():
    """Verifies that the rate limiter halts execution when max runs are reached."""
    state = get_autopilot_state()
    state["daily_runs_count"] = 999  # Artificially exceed max runs
    save_autopilot_state(state)

    mock_profile = {"auto_apply_settings": {"enabled": True, "max_runs_per_day": 5}}
    with patch("appliers.email_worker.load_profile", return_value=mock_profile):
        res = run_email_autopilot_batch(force=False)
        assert res["status"] == "rate_limited"
        assert "limit reached" in res["message"].lower()

    # Reset state
    state["daily_runs_count"] = 0
    save_autopilot_state(state)


def test_dry_run_leaves_database_unapplied():
    """Verifies that a dry-run evaluates targets without modifying DB application state."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT job_id FROM jobs WHERE apply_type = 'email' AND is_applied = 0 LIMIT 1")
    row = cursor.fetchone()
    conn.close()

    if not row:
        pytest.skip("No unapplied email jobs available for dry run test")

    job_id = row[0]

    res = run_email_autopilot_batch(force=True, dry_run=True, batch_limit=1)
    assert res["status"] in ("success", "no_jobs")

    # Verify DB still unapplied
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT is_applied FROM jobs WHERE job_id = ?", (job_id,))
    is_app = cursor.fetchone()[0]
    conn.close()

    assert is_app == 0


def test_simulated_email_batch_execution():
    """Tests execution of a 1-job batch with simulated delivery and verifies database tracking."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT job_id, apply_payload FROM jobs WHERE apply_type = 'email' LIMIT 1")
    row = cursor.fetchone()
    conn.close()

    assert row is not None
    job_id, orig_payload = row

    # Temporarily reset to unapplied
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE jobs SET is_applied = 0, apply_status = 'pending', relevance_score = 95 WHERE job_id = ?", (job_id,))
    conn.commit()
    conn.close()

    try:
        with patch("appliers.email_worker.send_smtp_email", return_value=True), \
             patch("appliers.email_worker.launch_outlook_compose", return_value={"status": "success"}):

            res = run_email_autopilot_batch(force=True, dry_run=False, batch_limit=1)
            assert res["status"] == "success"
            assert res["processed_count"] >= 1

            # Check DB was updated
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT is_applied, apply_status, applied_at, apply_payload FROM jobs WHERE job_id = ?", (job_id,))
            updated_row = cursor.fetchone()
            conn.close()

            assert updated_row[0] == 1
            assert updated_row[1] == "applied"
            assert updated_row[2] is not None
            payload_data = json.loads(updated_row[3])
            assert "sent_email" in payload_data
    finally:
        # Restore original state
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE jobs SET is_applied = 0, apply_status = 'pending', apply_payload = ? WHERE job_id = ?", (orig_payload, job_id))
        conn.commit()
        conn.close()
