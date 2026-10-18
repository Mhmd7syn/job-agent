import os
import sys
import json
import pytest
from fastapi.testclient import TestClient

# Ensure root dir is on path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from web.app import app
from core.applicant_profile import load_profile, save_profile, get_resume_for_role
from unittest.mock import patch, MagicMock
from appliers.email_generator import generate_email_draft
from appliers.gmail_launcher import build_gmail_compose_url, copy_file_to_clipboard, prepare_gmail_launch


@pytest.fixture
def client():
    return TestClient(app)


def test_cv_resolution_for_target_roles():
    """Verify that role titles resolve to configured resume paths from configurations."""
    import core.config as app_config

    roles = [
        "Data Analytics & BI",
        "Computer Vision & AI",
        "Data Science & Machine Learning",
        "Teaching & STEM Instructor"
    ]
    for role_query in roles:
        cv_path = get_resume_for_role(role_query)
        assert cv_path is not None, f"Should find CV path for {role_query}"
        assert os.path.exists(cv_path), f"CV file should exist at {cv_path}"
        matching_role = next((r for r in app_config.ROLES if r.get("title") == role_query), None)
        if matching_role and matching_role.get("resume_path"):
            assert os.path.normpath(cv_path) == os.path.normpath(matching_role["resume_path"])


def test_ai_unavailable_discards_and_notifies_telegram():
    """Verify that when AI client is unavailable, draft generation is discarded and Telegram is notified."""
    sample_job = {
        "job_id": "job-test-1",
        "title": "Data Analyst",
        "company": "Tech Corp",
        "location": "Cairo",
        "description": "Looking for a Data Analyst with SQL and Python skills.",
        "apply_payload": {"recipient_email": "hr@techcorp.com", "subject_hint": ""}
    }
    with patch("appliers.email_generator.client", None), \
         patch("appliers.email_generator.notify_telegram_candidate") as mock_tg:
        draft = generate_email_draft(job_data=sample_job)
        assert draft["status"] == "error"
        assert draft["reason"] == "ai_unavailable"
        assert "discarded" in draft["message"].lower()
        assert "body" not in draft
        assert mock_tg.called is True
        tg_call_msg = mock_tg.call_args[0][0]
        assert "Discarded" in tg_call_msg
        assert "Data Analyst" in tg_call_msg


def test_ai_generation_failure_discards_and_notifies_telegram():
    """Verify that when Gemini models fail, draft generation is discarded without heuristic fallback."""
    sample_job = {
        "job_id": "job-test-2",
        "title": "ML Engineer",
        "company": "AI Labs",
        "location": "Remote",
        "description": "Looking for ML Engineer with PyTorch experience.",
        "apply_payload": {"recipient_email": "careers@ailabs.com", "subject_hint": ""}
    }
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = RuntimeError("API quota exceeded")

    with patch("appliers.email_generator.client", mock_client), \
         patch("appliers.email_generator.notify_telegram_candidate") as mock_tg:
        draft = generate_email_draft(job_data=sample_job)
        assert draft["status"] == "error"
        assert draft["reason"] == "ai_unavailable"
        assert "quota exceeded" in draft["message"]
        assert "body" not in draft
        assert mock_tg.called is True
        tg_call_msg = mock_tg.call_args[0][0]
        assert "Discarded" in tg_call_msg
        assert "ML Engineer" in tg_call_msg


def test_gmail_compose_url_builder():
    """Verify Gmail compose URL is properly formed and encoded."""
    url = build_gmail_compose_url(
        recipient="hr@example.com",
        subject="Application for Data Scientist - Test Candidate",
        body="Dear Hiring Team,\n\nPlease find my application attached."
    )
    assert url.startswith("https://mail.google.com/mail/?")
    assert "to=hr%40example.com" in url
    assert "view=cm" in url
    assert "fs=1" in url
    assert "su=Application" in url
    assert "body=Dear" in url


def test_windows_clipboard_copy_file():
    """Verify copying a file to the clipboard works on Windows."""
    # Test on a known existing file
    test_file = os.path.join(BASE_DIR, "README.md")
    success = copy_file_to_clipboard(test_file)
    if sys.platform == "win32":
        assert success is True
    else:
        assert success is False


def test_prepare_gmail_launch():
    """Verify prepare_gmail_launch packages all metadata cleanly."""
    res = prepare_gmail_launch(
        recipient="test@example.com",
        subject="Test Subject",
        body="Hello world",
        cv_path=os.path.join(BASE_DIR, "AUTO_APPLY_QUEUE.md"),
        open_browser=False
    )
    assert res["status"] == "success"
    assert "https://mail.google.com/mail/?" in res["gmail_url"]
    assert res["recipient"] == "test@example.com"


def test_fastapi_generate_draft_endpoint(client):
    """Test /api/email/generate-draft with a mock or real DB job."""
    # Find a job with apply_type = 'email'
    import sqlite3
    from core.database import DB_PATH
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT job_id, title FROM jobs WHERE apply_type = 'email' LIMIT 1").fetchone()
    conn.close()

    if row:
        job_id = row[0]
        response = client.post("/api/email/generate-draft", json={"job_id": job_id})
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "success"
        assert "subject" in data
        assert "body" in data
        assert len(data["body"]) > 50
        assert "attached_cv" in data
        assert data["attached_cv"]["exists"] is True


def test_fastapi_open_in_gmail_endpoint(client):
    """Test /api/email/open-in-gmail endpoint."""
    response = client.post("/api/email/open-in-gmail", json={
        "job_id": "test-job-id",
        "recipient": "hr@test.com",
        "subject": "Test Role Application",
        "body": "Hello world",
        "cv_path": os.path.join(BASE_DIR, "AUTO_APPLY_QUEUE.md"),
        "open_browser": False
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "mail.google.com" in data["gmail_url"]


def test_fastapi_mark_applied_endpoint(client):
    """Test /api/email/mark-applied endpoint."""
    import sqlite3
    from core.database import DB_PATH
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT job_id FROM jobs WHERE apply_type = 'email' LIMIT 1").fetchone()
    conn.close()

    if row:
        job_id = row[0]
        response = client.post("/api/email/mark-applied", json={
            "job_id": job_id,
            "recipient": "test@domain.com",
            "subject": "Test Subject",
            "body": "Test body"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["job_id"] == job_id

        # Verify DB state updated
        conn = sqlite3.connect(DB_PATH)
        updated_row = conn.execute("SELECT is_applied, apply_status, applied_at FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        conn.close()
        assert updated_row[0] == 1
        assert updated_row[1] == "applied"
        assert updated_row[2] is not None


def test_email_system_prompt_sections():
    """Verify that EMAIL_SYSTEM_PROMPT explicitly specifies separated sections."""
    from appliers.email_generator import EMAIL_SYSTEM_PROMPT

    assert "Salutation" in EMAIL_SYSTEM_PROMPT
    assert "Opening" in EMAIL_SYSTEM_PROMPT
    assert "Key Highlights" in EMAIL_SYSTEM_PROMPT
    assert "Closing" in EMAIL_SYSTEM_PROMPT
    assert "separated" in EMAIL_SYSTEM_PROMPT.lower()
    assert "blank line" in EMAIL_SYSTEM_PROMPT.lower()


def test_fastapi_send_direct_smtp_marks_applied_and_passes_subject(client):
    """Test /api/email/send-direct-smtp dispatches with subject and marks job as applied in DB."""
    import sqlite3
    from core.database import DB_PATH

    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT job_id, apply_payload FROM jobs WHERE apply_type = 'email' LIMIT 1").fetchone()
    conn.close()

    if not row:
        pytest.skip("No email jobs in DB for testing send-direct-smtp")

    job_id, orig_payload = row

    mock_profile = {
        "auto_apply_settings": {
            "smtp_host": "smtp.test.com",
            "smtp_port": 465,
            "smtp_email": "sender@test.com",
            "smtp_app_password": "testpassword1234"
        },
        "personal_info": {"full_name": "Test Candidate"}
    }

    # Reset job state to unapplied
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE jobs SET is_applied = 0, apply_status = 'pending' WHERE job_id = ?", (job_id,))
    conn.commit()
    conn.close()

    try:
        with patch("web.routers.copilots.load_profile", return_value=mock_profile), \
             patch("web.routers.copilots.send_smtp_email", return_value=True) as mock_send:

            test_subject = "Application for Senior Engineer - Test Candidate"
            response = client.post("/api/email/send-direct-smtp", json={
                "job_id": job_id,
                "recipient": "hr@techcorp.com",
                "subject": test_subject,
                "body": "Hello hiring team,\n\nPlease review my application.",
                "cv_path": None
            })

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert data["job_id"] == job_id

            # Verify send_smtp_email received the subject
            mock_send.assert_called_once()
            call_kwargs = mock_send.call_args[1]
            assert call_kwargs["subject"] == test_subject
            assert call_kwargs["recipient_email"] == "hr@techcorp.com"

            # Verify DB was marked as applied
            conn = sqlite3.connect(DB_PATH)
            updated_row = conn.execute(
                "SELECT is_applied, apply_status, applied_at, apply_channel, apply_payload FROM jobs WHERE job_id = ?",
                (job_id,)
            ).fetchone()
            conn.close()

            assert updated_row[0] == 1
            assert updated_row[1] == "applied"
            assert updated_row[2] is not None
            assert updated_row[3] == "email"
            saved_payload = json.loads(updated_row[4])
            assert "sent_email" in saved_payload
            assert saved_payload["sent_email"]["subject"] == test_subject
            assert saved_payload["sent_email"]["delivery_method"] == "smtp_copilot"
    finally:
        # Restore DB state
        conn = sqlite3.connect(DB_PATH)
        conn.execute("UPDATE jobs SET is_applied = 0, apply_status = 'pending', apply_payload = ? WHERE job_id = ?", (orig_payload, job_id))
        conn.commit()
        conn.close()


def test_is_confidential_company_helper():
    """Verify is_confidential_company correctly identifies confidential and generic names."""
    from core.job_utils import is_confidential_company

    assert is_confidential_company("Confidential") is True
    assert is_confidential_company("confidential") is True
    assert is_confidential_company("Confidential Company") is True
    assert is_confidential_company("Unknown") is True
    assert is_confidential_company("Company") is True
    assert is_confidential_company("Not specified") is True
    assert is_confidential_company("") is True
    assert is_confidential_company(None) is True

    assert is_confidential_company("Google") is False
    assert is_confidential_company("Siemens") is False
    assert is_confidential_company("Tech Solutions LLC") is False


def test_email_draft_does_not_pass_confidential_company_to_llm():
    """Verify company name is NOT passed to the LLM call when marked confidential."""
    sample_job = {
        "job_id": "job-conf-1",
        "title": "AI Engineer",
        "company": "Confidential",
        "location": "Cairo, Egypt",
        "description": "Looking for an AI Engineer experienced with Python and LLMs.",
        "apply_payload": {"recipient_email": "jobs@confidential.com", "subject_hint": ""}
    }

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "body": "Dear Hiring Team,\n\nI'm reaching out to apply for the AI Engineer position.\n\n• Built scalable LLM workflows.\n• Shipped production models.\n\nI've attached my resume for your review and would welcome the opportunity to discuss my fit."
    })
    mock_client.models.generate_content.return_value = mock_response

    with patch("appliers.email_generator.client", mock_client):
        result = generate_email_draft(job_data=sample_job)

        assert result["status"] == "success"

        # Check call arguments to client.models.generate_content
        mock_client.models.generate_content.assert_called_once()
        call_kwargs = mock_client.models.generate_content.call_args[1]
        user_prompt = call_kwargs["contents"]

        # Ensure company name is NOT in the prompt passed to the LLM
        assert "Position: AI Engineer" in user_prompt
        assert "at Confidential" not in user_prompt
        assert "Company: Confidential" not in user_prompt
        assert "Confidential" not in user_prompt

        # Ensure output body contains the position without 'at Confidential'
        assert "at Confidential" not in result["body"]
        assert "I'm reaching out to apply for the AI Engineer position." in result["body"]


def test_email_draft_passes_real_company_to_llm():
    """Verify company name IS passed to the LLM call when company is known and not confidential."""
    sample_job = {
        "job_id": "job-real-1",
        "title": "AI Engineer",
        "company": "Tech Corp",
        "location": "Remote",
        "description": "Looking for an AI Engineer experienced with Python.",
        "apply_payload": {"recipient_email": "jobs@techcorp.com", "subject_hint": ""}
    }

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "body": "Dear Hiring Team,\n\nI'm reaching out to apply for the AI Engineer position at Tech Corp.\n\n• Built ML pipelines.\n\nI've attached my resume for your review and would welcome the opportunity to discuss my fit."
    })
    mock_client.models.generate_content.return_value = mock_response

    with patch("appliers.email_generator.client", mock_client):
        result = generate_email_draft(job_data=sample_job)

        assert result["status"] == "success"
        call_kwargs = mock_client.models.generate_content.call_args[1]
        user_prompt = call_kwargs["contents"]

        # Real company should be included in prompt
        assert "Position: AI Engineer at Tech Corp" in user_prompt
        assert "Tech Corp" in result["body"]



