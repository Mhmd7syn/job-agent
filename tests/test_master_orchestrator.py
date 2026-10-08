import os
import sqlite3
import pytest
from fastapi.testclient import TestClient

from web.app import app
from appliers.master_orchestrator import (
    run_master_autopilot_cycle,
    get_applications_history,
    get_applications_aggregate_stats,
    resolve_telegram_hitl_answer
)
from core.applicant_profile import load_profile, save_profile
from core.database import DB_PATH

client = TestClient(app)


def test_autopilot_status_and_stats_api():
    """Verifies that Auto-Pilot status and aggregate metrics return valid figures."""
    status_res = client.get("/api/autopilot/status")
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert "daily_runs_count" in status_data
    assert "emails_sent_today" in status_data
    assert "is_cycle_running" in status_data
    assert "is_enabled" in status_data
    assert "is_paused" in status_data

    stats_res = client.get("/api/applications/stats")
    assert stats_res.status_code == 200
    stats_data = stats_res.json()
    assert "total_applied_all_time" in stats_data
    assert "channel_breakdown" in stats_data
    assert "runs_remaining" in stats_data
    assert "is_enabled" in stats_data
    assert "is_paused" in stats_data


def test_applications_history_api():
    """Verifies that applications history endpoint lists applied jobs with channel and search filters."""
    res_all = client.get("/api/applications/history?channel=all&limit=10")
    assert res_all.status_code == 200
    data_all = res_all.json()
    assert "total" in data_all
    assert "applications" in data_all
    assert isinstance(data_all["applications"], list)

    # Filter by specific channel
    res_email = client.get("/api/applications/history?channel=email&limit=10")
    assert res_email.status_code == 200

    # Search filter
    res_search = client.get("/api/applications/history?search=data&limit=10")
    assert res_search.status_code == 200


def test_telegram_hitl_question_and_answer_cycle():
    """
    Verifies that resolving a Telegram HITL question stores the answer permanently
    in candidate_profile.json (custom_qa_pairs).
    """
    profile = load_profile()
    orig_qa = dict(profile.get("custom_qa_pairs", {}))

    test_q = "Do you have experience with Apache Kafka?"
    test_a = "Yes, 2 years building event-driven streaming pipelines."
    test_job_id = "test_hitl_mock_job"

    try:
        success = resolve_telegram_hitl_answer(
            job_id=test_job_id,
            question=test_q,
            answer=test_a
        )
        assert success is True

        # Check candidate_profile.json
        updated_profile = load_profile()
        qa_pairs = updated_profile.get("custom_qa_pairs", {})
        assert test_q in qa_pairs
        assert qa_pairs[test_q] == test_a
    finally:
        # Restore original custom_qa_pairs
        profile["custom_qa_pairs"] = orig_qa
        save_profile(profile)


def test_applications_retry_api():
    """Verifies that the /api/applications/retry endpoint resets job state to pending."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT job_id FROM jobs LIMIT 1")
    job_id = cursor.fetchone()[0]

    # Set as applied temporarily
    cursor.execute("UPDATE jobs SET is_applied = 1, apply_status = 'applied' WHERE job_id = ?", (job_id,))
    conn.commit()
    conn.close()

    try:
        retry_res = client.post("/api/applications/retry", json={"job_id": job_id})
        assert retry_res.status_code == 200
        assert retry_res.json()["status"] == "success"

        # Check DB was reset
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT is_applied, apply_status FROM jobs WHERE job_id = ?", (job_id,))
        row = c.fetchone()
        conn.close()

        assert row[0] == 0
        assert row[1] == "pending"
    finally:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE jobs SET is_applied = 0, apply_status = 'pending' WHERE job_id = ?", (job_id,))
        conn.commit()
        conn.close()


def test_master_autopilot_cycle_dry_run():
    """Verifies end-to-end master cycle execution across multi-channel pipeline."""
    res = run_master_autopilot_cycle(force=True, dry_run=True)
    assert res["status"] == "success"
    assert "results" in res
    assert "email_batch" in res["results"]
    assert "whatsapp_batch" in res["results"]


def test_master_autopilot_cycle_paused_by_default():
    """Verifies that the master auto-pilot cycle is paused by default when force=False."""
    # Ensure profile is paused
    client.post("/api/autopilot/toggle-state", json={"enabled": False})

    res = run_master_autopilot_cycle(force=False)
    assert res["status"] == "paused"
    assert "paused" in res["message"].lower()


def test_toggle_autopilot_state_api():
    """Verifies the /api/autopilot/toggle-state endpoint resumes and pauses Auto-Pilot."""
    try:
        # Resume
        res_resume = client.post("/api/autopilot/toggle-state", json={"enabled": True})
        assert res_resume.status_code == 200
        assert res_resume.json()["enabled"] is True
        assert res_resume.json()["is_paused"] is False

        # Status endpoint reflects active
        status_data = client.get("/api/autopilot/status").json()
        assert status_data["is_enabled"] is True
        assert status_data["is_paused"] is False

        # Pause again
        res_pause = client.post("/api/autopilot/toggle-state", json={"enabled": False})
        assert res_pause.status_code == 200
        assert res_pause.json()["enabled"] is False
        assert res_pause.json()["is_paused"] is True

        # Status endpoint reflects paused
        status_data_2 = client.get("/api/autopilot/status").json()
        assert status_data_2["is_enabled"] is False
        assert status_data_2["is_paused"] is True
    finally:
        # Guarantee it remains paused
        client.post("/api/autopilot/toggle-state", json={"enabled": False})
