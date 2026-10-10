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
    """Verify that role titles resolve to real role-matching CV PDFs."""
    roles = [
        ("Data Analytics & BI", "Data Analytics & BI"),
        ("Computer Vision & AI", "Computer Vision & AI"),
        ("Data Science & Machine Learning", "Data Science & Machine Learning"),
        ("Teaching & STEM Instructor", "Teaching & STEM Instructor")
    ]
    for role_query, expected_folder in roles:
        cv_path = get_resume_for_role(role_query)
        assert cv_path is not None, f"Should find CV path for {role_query}"
        assert os.path.exists(cv_path), f"CV file should exist at {cv_path}"
        assert expected_folder in cv_path, f"CV path should be in folder {expected_folder}"


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
        subject="Application for Data Scientist - Mohamed Hussein",
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
    test_file = os.path.join(BASE_DIR, "AUTO_APPLY_QUEUE.md")
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
