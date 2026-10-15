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
    """Verify candidate profile has the saved signature configured from settings."""
    profile = load_profile()
    auto_apply = profile.get("auto_apply_settings", {})
    sig_path = auto_apply.get("email_signature_path") or auto_apply.get("email_signature_personal", "")
    assert sig_path is not None
    assert len(sig_path.strip()) > 0


def test_outlook_launcher_unit_structure():
    """Verify launch_outlook_compose returns expected keys and handles missing files gracefully."""
    res = launch_outlook_compose(
        recipient="hr@testcompany.com",
        subject="Application for Data Scientist",
        body="Dear Hiring Team,\n\nTest body.",
        cv_path=os.path.join(BASE_DIR, "README.md")
    )
    # On Windows with Outlook installed, it should succeed
    if sys.platform == "win32":
        assert res["status"] == "success"
        assert "outlook" in res["client"]
        assert res["recipient"] == "hr@testcompany.com"
        assert res["attached"] is True
        assert res["cv_filename"] == "README.md"


def test_email_prompt_instructs_signature_added_manually():
    """Verify that email prompts explicitly instruct the AI once at the system prompt that signature will be added manually."""
    from appliers.email_generator import EMAIL_SYSTEM_PROMPT

    assert "signature will be added manually" in EMAIL_SYSTEM_PROMPT.lower()
    assert "output only the email body" in EMAIL_SYSTEM_PROMPT.lower()


def test_fastapi_open_in_outlook_endpoint(client):
    """Test POST /api/email/open-in-outlook endpoint."""
    res = client.post("/api/email/open-in-outlook", json={
        "recipient": "recruiter@example.com",
        "subject": "Role Application",
        "body": "Dear Hiring Team,\n\nTest application body.",
        "raw_body": "Dear Hiring Team,\n\nTest application body.",
        "cv_path": os.path.join(BASE_DIR, "README.md"),
        "personal_signature": "Best regards,\nCandidate"
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
    cursor.execute("SELECT job_id FROM jobs WHERE (is_applied = 0 OR is_applied IS NULL) AND (apply_status IS NULL OR apply_status != 'applied') AND apply_type = 'email' LIMIT 1")
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
            "cv_path": os.path.join(BASE_DIR, "README.md")
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
            "cv_path": os.path.join(BASE_DIR, "README.md")
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


def test_outlook_signature_format():
    """Verify Outlook signature format is loaded from configuration and formatted safely."""
    from core.email_signature import (
        get_signature_from_config,
        format_email_body_html,
        strip_signoff_from_body
    )

    sig = get_signature_from_config()
    assert isinstance(sig, str)
    assert len(sig.strip()) > 0

    # Test stripping signoff
    body_with_sig = f"Dear Hiring Team,\n\nI want to apply.\n\n{sig}"
    stripped = strip_signoff_from_body(body_with_sig)
    assert "I want to apply." in stripped

    # Test complete HTML conversion preserving signature from config
    full_html = format_email_body_html(body_with_sig, signature=sig)
    assert "<body" in full_html
    assert "I want to apply." in full_html


def test_signature_path_from_config_loads_html(tmp_path):
    """Verify loading and parsing signature from a configured HTML file path."""
    from core.email_signature import (
        get_signature_html,
        get_signature_text,
        format_email_body_html
    )

    html_file = tmp_path / "custom_signature.html"
    html_file.write_text("""<!DOCTYPE html>
<html>
<body>
  <table>
    <tr><td>Best Regards,</td></tr>
    <tr><td>Jane Doe</td></tr>
    <tr><td>Lead AI Engineer</td></tr>
    <tr><td><a href="https://linkedin.com"><img src="icon.png" alt="LinkedIn"/></a></td></tr>
  </table>
</body>
</html>""", encoding="utf-8")

    mock_prof = {
        "auto_apply_settings": {
            "email_signature_path": str(html_file)
        }
    }

    html_sig = get_signature_html(profile=mock_prof)
    assert "Jane Doe" in html_sig
    assert "<table" in html_sig
    assert "<!DOCTYPE" not in html_sig  # Cleanly extracted inner body

    text_sig = get_signature_text(profile=mock_prof)
    assert "Jane Doe" in text_sig
    assert "Best Regards" in text_sig
    assert "Lead AI Engineer" in text_sig
    assert "LinkedIn" in text_sig

    full_email = format_email_body_html("Hello world,", signature=html_sig)
    assert "<body" in full_email
    assert "Jane Doe" in full_email
    assert "<table" in full_email


def test_actual_user_configured_signature_file():
    """Verify user's configured signature HTML file if present on disk."""
    import json
    from core.applicant_profile import PROFILE_PATH
    from core.email_signature import get_signature_html, get_signature_text

    # Read base profile directly to bypass test fixture monkeypatch
    base_profile_path = os.path.join(BASE_DIR, "core", "candidate_profile.json")
    if os.path.exists(base_profile_path):
        with open(base_profile_path, "r", encoding="utf-8") as f:
            real_profile = json.load(f)

        sig_path = real_profile.get("auto_apply_settings", {}).get("email_signature_path", "")
        assert sig_path != "", "email_signature_path should be specified in candidate_profile.json"
        if os.path.exists(sig_path):
            html_sig = get_signature_html(profile=real_profile)
            assert "Mohamed Hussein" in html_sig
            assert "AI Engineer" in html_sig

            text_sig = get_signature_text(profile=real_profile)
            assert "Mohamed Hussein" in text_sig
            assert "AI Engineer" in text_sig
            assert "LinkedIn" in text_sig


