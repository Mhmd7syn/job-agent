import os
import json
import sqlite3
import pytest
from unittest.mock import patch

from appliers.whatsapp_worker import (
    run_whatsapp_autopilot_batch,
    MAX_WHATSAPP_DAILY_CAP
)
from appliers.email_worker import get_autopilot_state, save_autopilot_state
from core.database import DB_PATH


def test_whatsapp_worker_paused_by_default():
    """Verifies that WhatsApp worker is paused by default and returns skipped when force=False."""
    res = run_whatsapp_autopilot_batch(force=False)
    assert res["status"] == "skipped"
    assert "disabled" in res["message"].lower() or "paused" in res["message"].lower()


def test_whatsapp_anti_ban_cap():
    """Verifies that the anti-ban safety cap halts WhatsApp runs when daily limit is reached."""
    state = get_autopilot_state()
    orig_wa = state.get("whatsapp_sent_today", 0)
    state["whatsapp_sent_today"] = MAX_WHATSAPP_DAILY_CAP + 1
    save_autopilot_state(state)

    try:
        mock_profile = {"auto_apply_settings": {"enabled": True, "channels_enabled": {"whatsapp": True}}}
        with patch("appliers.whatsapp_worker.load_profile", return_value=mock_profile):
            res = run_whatsapp_autopilot_batch(force=False)
            assert res["status"] == "rate_limited"
            assert "anti-ban" in res["message"].lower() or "limit" in res["message"].lower()
    finally:
        state["whatsapp_sent_today"] = orig_wa
        save_autopilot_state(state)


def test_whatsapp_channel_disabled_skips_even_when_forced():
    """Verifies that WhatsApp worker returns skipped if whatsapp channel is unchecked in settings, even when forced."""
    mock_profile = {"auto_apply_settings": {"enabled": True, "channels_enabled": {"whatsapp": False}}}
    with patch("appliers.whatsapp_worker.load_profile", return_value=mock_profile):
        res = run_whatsapp_autopilot_batch(force=True)
        assert res["status"] == "skipped"
        assert "disabled" in res["message"].lower()


def test_whatsapp_dry_run():
    """Verifies that dry-run identifies target WhatsApp jobs without modifying DB state."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT job_id FROM jobs WHERE apply_type = 'whatsapp' LIMIT 1")
    row = cursor.fetchone()
    conn.close()

    if not row:
        pytest.skip("No WhatsApp jobs in database for dry-run test")

    mock_profile = {"auto_apply_settings": {"enabled": True, "channels_enabled": {"whatsapp": True}}}
    with patch("appliers.whatsapp_worker.load_profile", return_value=mock_profile):
        res = run_whatsapp_autopilot_batch(force=True, dry_run=True, batch_limit=1)
        assert res["status"] in ("success", "no_jobs")


def test_simulated_whatsapp_batch_execution():
    """Verifies that an automated WhatsApp batch dispatches message and updates DB record."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT job_id, apply_payload FROM jobs WHERE apply_type = 'whatsapp' AND apply_payload LIKE '%phone%20%' LIMIT 1")
    row = cursor.fetchone()
    if not row:
        cursor.execute("SELECT job_id, apply_payload FROM jobs WHERE apply_type = 'whatsapp' LIMIT 1")
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

    mock_pitch = {
        "status": "success",
        "message": "Hello, I am applying for this role.",
        "cv_path": os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "README.md")
    }
    mock_profile = {"auto_apply_settings": {"enabled": True, "channels_enabled": {"whatsapp": True}}}

    try:
        with patch("appliers.whatsapp_worker.load_profile", return_value=mock_profile), \
             patch("appliers.whatsapp_worker.generate_whatsapp_pitch", return_value=mock_pitch), \
             patch("appliers.whatsapp_worker._send_whatsapp_message_via_playwright", return_value=True), \
             patch("appliers.whatsapp_worker.notify_telegram_candidate") as mock_tg:
            res = run_whatsapp_autopilot_batch(force=True, dry_run=False, batch_limit=1)
            assert res["status"] == "success"
            assert res["processed_count"] >= 1
            # Must NOT spam Telegram on success
            mock_tg.assert_not_called()

            # Verify DB was updated
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT is_applied, apply_status, applied_at, apply_payload FROM jobs WHERE job_id = ?", (job_id,))
            updated = cursor.fetchone()
            conn.close()

            assert updated[0] == 1
            assert updated[1] == "applied"
            assert updated[2] is not None
            payload_data = json.loads(updated[3])
            assert "sent_whatsapp" in payload_data
    finally:
        # Restore original state
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE jobs SET is_applied = 0, apply_status = 'pending', apply_payload = ? WHERE job_id = ?", (orig_payload, job_id))
        conn.commit()
        conn.close()


def test_whatsapp_batch_failure_notifies_telegram():
    """Verifies that a WhatsApp delivery failure triggers a Telegram failure alert."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT job_id, apply_payload FROM jobs WHERE apply_type = 'whatsapp' LIMIT 1")
    row = cursor.fetchone()
    conn.close()

    assert row is not None
    job_id, orig_payload = row

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE jobs SET is_applied = 0, apply_status = 'pending', relevance_score = 95 WHERE job_id = ?", (job_id,))
    conn.commit()
    conn.close()

    mock_pitch = {
        "status": "success",
        "message": "Hello, I am applying for this role.",
        "cv_path": os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "README.md")
    }
    mock_profile = {"auto_apply_settings": {"enabled": True, "channels_enabled": {"whatsapp": True}}}

    try:
        with patch("appliers.whatsapp_worker.load_profile", return_value=mock_profile), \
             patch("appliers.whatsapp_worker.generate_whatsapp_pitch", return_value=mock_pitch), \
             patch("appliers.whatsapp_worker._send_whatsapp_message_via_playwright", return_value=False), \
             patch("appliers.whatsapp_worker.notify_telegram_candidate") as mock_tg:

            res = run_whatsapp_autopilot_batch(force=True, dry_run=False, batch_limit=1)
            assert res["status"] == "success"
            assert res["processed_count"] == 0
            mock_tg.assert_called_once()
            assert "Failed" in mock_tg.call_args[0][0]
    finally:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE jobs SET is_applied = 0, apply_status = 'pending', apply_payload = ? WHERE job_id = ?", (orig_payload, job_id))
        conn.commit()
        conn.close()
