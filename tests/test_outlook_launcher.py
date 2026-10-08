import os
import sys
import pytest
from fastapi.testclient import TestClient

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from web.app import app
from appliers.outlook_launcher import launch_outlook_compose
from core.applicant_profile import load_profile

@pytest.fixture
def client():
    return TestClient(app)


def test_candidate_profile_has_personal_signature():
    """Verify candidate profile has the saved personal signature configured."""
    profile = load_profile()
    auto_apply = profile.get("auto_apply_settings", {})
    sig = auto_apply.get("email_signature_personal", "")
    assert sig is not None
    assert len(sig.strip()) > 0
    assert "Mohamed Hussein" in sig
    assert "mohamedh2910@gmail.com" in sig


def test_outlook_launcher_unit_structure():
    """Verify launch_outlook_compose returns expected keys and handles missing files gracefully."""
    res = launch_outlook_compose(
        recipient="hr@testcompany.com",
        subject="Application for Data Scientist",
        body="Dear Hiring Team,\n\nTest body.",
        cv_path=os.path.join(BASE_DIR, "AUTO_APPLY_QUEUE.md")
    )
    # On Windows with Outlook installed, it should succeed
    if sys.platform == "win32":
        assert res["status"] == "success"
        assert "outlook" in res["client"]
        assert res["recipient"] == "hr@testcompany.com"
        assert res["attached"] is True
        assert res["cv_filename"] == "AUTO_APPLY_QUEUE.md"


def test_signature_deduplication_exact():
    """Verify that append_signature_safely completely eliminates duplicate 'Best regards, Mohamed Hussein'."""
    from appliers.email_generator import append_signature_safely

    ai_body = "Dear Hiring Team at Company,\n\nI am thrilled to apply for the position.\n\nBest regards,\nMohamed Hussein"
    personal_sig = "Best regards,\nMohamed Hussein\nmohamedh2910@gmail.com | +20 109 734 4958\nLinkedIn: linkedin.com/in/Mhmd7syn"

    result = append_signature_safely(ai_body, personal_sig, "Mohamed Hussein")
    assert result.count("Best regards") == 1
    assert result.count("Mohamed Hussein") == 1
    assert "mohamedh2910@gmail.com" in result
    assert "+20 109 734 4958" in result


def test_fastapi_open_in_outlook_endpoint(client):
    """Test POST /api/email/open-in-outlook endpoint."""
    res = client.post("/api/email/open-in-outlook", json={
        "recipient": "recruiter@example.com",
        "subject": "Role Application",
        "body": "Dear Hiring Team,\n\nTest application body.",
        "raw_body": "Dear Hiring Team,\n\nTest application body.",
        "cv_path": os.path.join(BASE_DIR, "AUTO_APPLY_QUEUE.md"),
        "personal_signature": "Best regards,\nMohamed Hussein"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert "outlook" in data["client"]
    assert data["recipient"] == "recruiter@example.com"
    assert data["attached"] is True


def test_co_pilot_does_not_auto_mark_applied(client):
    """Crucial Co-Pilot Rule: Opening Outlook or Gmail must NOT mark the job applied in DB."""
    import sqlite3
    from core.database import DB_PATH

    conn = sqlite3.connect(DB_PATH)
    # Pick or insert a test job that is unapplied
    cursor = conn.cursor()
    cursor.execute("SELECT job_id FROM jobs WHERE (is_applied = 0 OR is_applied IS NULL) AND apply_type = 'email' LIMIT 1")
    row = cursor.fetchone()
    if not row:
        # Reset one for test
        cursor.execute("SELECT job_id FROM jobs WHERE apply_type = 'email' LIMIT 1")
        row = cursor.fetchone()
        if row:
            cursor.execute("UPDATE jobs SET is_applied = 0, apply_status = 'pending' WHERE job_id = ?", (row[0],))
            conn.commit()

    conn.close()

    if row:
        test_job_id = row[0]

        # 1. Call open-in-outlook
        res = client.post("/api/email/open-in-outlook", json={
            "job_id": test_job_id,
            "recipient": "hr@verify-unapplied.com",
            "subject": "Test Unapplied Flow",
            "body": "Test body",
            "cv_path": os.path.join(BASE_DIR, "AUTO_APPLY_QUEUE.md")
        })
        assert res.status_code == 200

        # Verify job is STILL unapplied
        conn = sqlite3.connect(DB_PATH)
        check = conn.execute("SELECT is_applied, apply_status FROM jobs WHERE job_id = ?", (test_job_id,)).fetchone()
        conn.close()
        assert check[0] == 0 or check[0] is None
        assert check[1] != "applied"

        # 2. Call open-in-gmail
        res_g = client.post("/api/email/open-in-gmail", json={
            "job_id": test_job_id,
            "recipient": "hr@verify-unapplied.com",
            "subject": "Test Unapplied Flow Gmail",
            "body": "Test body",
            "cv_path": os.path.join(BASE_DIR, "AUTO_APPLY_QUEUE.md")
        })
        assert res_g.status_code == 200

        # Verify job is STILL unapplied
        conn = sqlite3.connect(DB_PATH)
        check = conn.execute("SELECT is_applied, apply_status FROM jobs WHERE job_id = ?", (test_job_id,)).fetchone()
        conn.close()
        assert check[0] == 0 or check[0] is None
        assert check[1] != "applied"

        # 3. Only when explicit mark-applied is called should it change
        res_applied = client.post("/api/email/mark-applied", json={
            "job_id": test_job_id,
            "recipient": "hr@verify-unapplied.com",
            "subject": "Test Unapplied Flow",
            "body": "Test body",
            "applied_via": "outlook_copilot"
        })
        assert res_applied.status_code == 200

        conn = sqlite3.connect(DB_PATH)
        check = conn.execute("SELECT is_applied, apply_status FROM jobs WHERE job_id = ?", (test_job_id,)).fetchone()
        conn.close()
        assert check[0] == 1
        assert check[1] == "applied"
