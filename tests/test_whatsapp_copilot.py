import os
import sys
import json
import sqlite3
import pytest
from fastapi.testclient import TestClient

# Ensure root dir is on sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from web.app import app
from core.database import DB_PATH
from core.applicant_profile import get_resume_for_role
from appliers.whatsapp_copilot import (
    normalize_phone_number,
    build_wa_me_url,
    build_whatsapp_web_url,
    format_whatsapp_pitch,
    generate_fallback_pitch,
    generate_whatsapp_pitch
)
from appliers.whatsapp_launcher import launch_whatsapp_web


@pytest.fixture
def client():
    return TestClient(app)


def test_phone_normalization():
    """Verify phone normalization for Egyptian, Gulf, and international formats."""
    assert normalize_phone_number("01000000000") == "201000000000"
    assert normalize_phone_number("+20 10 0000 0000") == "201000000000"
    assert normalize_phone_number("00201100000000") == "201100000000"
    assert normalize_phone_number("01100000000") == "201100000000"
    assert normalize_phone_number("01551234567") == "201551234567"
    assert normalize_phone_number("01221234567") == "201221234567"
    assert normalize_phone_number("0501234567") in ("966501234567", "971501234567")
    assert normalize_phone_number("+966 50 123 4567") == "966501234567"


def test_url_builders():
    """Verify protocol URL formats for wa.me and WhatsApp Web."""
    wa_me_url = build_wa_me_url("201000000000", "Hello Candidate")
    assert wa_me_url.startswith("https://wa.me/201000000000?text=")
    assert "Hello%20Candidate" in wa_me_url

    web_url = build_whatsapp_web_url("201000000000", "Hello Candidate")
    assert web_url.startswith("https://web.whatsapp.com/send?phone=201000000000&text=")
    assert "Hello%20Candidate" in web_url


def test_fallback_pitch_generation():
    """Verify fallback pitch creates clean, professional English text with candidate details."""
    pitch_data = generate_fallback_pitch(
        job_title="Data Analyst",
        company="Retail Corp",
        candidate_name="Candidate Name",
        cv_path=None,
        candidate_phone="+201000000000",
        candidate_email="applicant@example.com",
        linkedin_url="https://linkedin.com/in/applicant"
    )
    assert pitch_data["status"] == "success"
    pitch_text = pitch_data["pitch"]
    assert "Data Analyst" in pitch_text
    assert "Retail Corp" in pitch_text
    assert "Candidate Name" in pitch_text
    assert "resume" in pitch_text.lower() or "cv" in pitch_text.lower()
    assert "+201000000000" in pitch_text
    assert "linkedin.com/in/applicant" in pitch_text


def test_cv_resolution_for_whatsapp_roles():
    """Verify that roles corresponding to WhatsApp postings resolve to configured CV PDFs from configuration."""
    import core.config as app_config

    cv_teaching = get_resume_for_role("CS8 Instructor")
    assert cv_teaching is not None
    assert os.path.exists(cv_teaching)
    expected_teaching_cv = next((r.get("resume_path") for r in app_config.ROLES if "Instructor" in r.get("title", "")), None)
    if expected_teaching_cv:
        assert os.path.normpath(cv_teaching) == os.path.normpath(expected_teaching_cv)

    cv_analytics = get_resume_for_role("Data Analyst")
    assert cv_analytics is not None
    assert os.path.exists(cv_analytics)
    expected_analytics_cv = next((r.get("resume_path") for r in app_config.ROLES if "Data Analytics" in r.get("title", "")), None)
    if expected_analytics_cv:
        assert os.path.normpath(cv_analytics) == os.path.normpath(expected_analytics_cv)


def test_api_generate_pitch_endpoint(client):
    """Test /api/whatsapp/generate-pitch returns structured pitch with real CV path."""
    response = client.post("/api/whatsapp/generate-pitch", json={"job_id": "cs8 instructor|eraasoft"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "phone" in data
    assert len(data["phone"]) >= 10
    assert "pitch" in data
    assert len(data["pitch"]) > 20
    assert "attached_cv" in data
    expected_cv = get_resume_for_role("Teaching & STEM Instructor")
    if expected_cv:
        assert data["attached_cv"]["filename"] == os.path.basename(expected_cv)
    else:
        assert data["attached_cv"]["filename"].lower().endswith(".pdf")
    assert data["attached_cv"]["exists"] is True


def test_api_copy_cv_endpoint(client):
    """Test /api/whatsapp/copy-cv endpoint with valid and invalid CV paths."""
    cv_path = get_resume_for_role("Data Analytics & BI")
    if cv_path and os.path.exists(cv_path):
        resp = client.post("/api/whatsapp/copy-cv", json={"cv_path": cv_path})
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

    bad_resp = client.post("/api/whatsapp/copy-cv", json={"cv_path": "C:\\nonexistent\\cv.pdf"})
    assert bad_resp.status_code == 404


def test_decoupled_apply_workflow(client):
    """Verify that generating a pitch does NOT mark a job as applied until explicit endpoint call."""
    test_job_id = "cs8 instructor|eraasoft"

    # Verify initial state in DB
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT is_applied, apply_status FROM jobs WHERE job_id = ?", (test_job_id,))
    row = cursor.fetchone()
    initial_applied = row[0] if row else 0

    # Reset to 0 for test
    cursor.execute("UPDATE jobs SET is_applied = 0, apply_status = 'unapplied' WHERE job_id = ?", (test_job_id,))
    conn.commit()
    conn.close()

    # Call generate-pitch: should leave job unapplied!
    gen_resp = client.post("/api/whatsapp/generate-pitch", json={"job_id": test_job_id})
    assert gen_resp.status_code == 200

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT is_applied, apply_status FROM jobs WHERE job_id = ?", (test_job_id,))
    row = cursor.fetchone()
    conn.close()
    assert row[0] == 0, "Generating pitch must NOT mark job as applied!"

    # Call explicit mark-applied endpoint
    mark_resp = client.post("/api/whatsapp/mark-applied", json={
        "job_id": test_job_id,
        "phone": "201000000000",
        "pitch": "Test pitch message",
        "applied_via": "whatsapp_edge"
    })
    assert mark_resp.status_code == 200
    assert mark_resp.json()["status"] == "success"

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT is_applied, apply_status, apply_payload FROM jobs WHERE job_id = ?", (test_job_id,))
    row = cursor.fetchone()
    conn.close()
    assert row[0] == 1
    assert row[1] == "applied"
    payload = json.loads(row[2]) if isinstance(row[2], str) else row[2]
    assert "sent_whatsapp" in payload
    assert payload["sent_whatsapp"]["phone"] == "201000000000"

    # Restore initial state
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE jobs SET is_applied = ?, apply_status = ? WHERE job_id = ?", (initial_applied, "applied" if initial_applied else "unapplied", test_job_id))
    conn.commit()
    conn.close()


def test_format_whatsapp_pitch_multi_paragraph():
    """Verify that format_whatsapp_pitch enforces multi-paragraph structure with double line breaks."""
    # 1. Single collapsed line from LLM
    single_line = (
        "Hello Eraasoft Hiring Team, I'm reaching out regarding the CS8 Instructor role. "
        "I have 4 years of teaching experience. I developed full-stack curriculum. "
        "Looking forward to hearing from you. Best regards, Mohamed Hussein +201000000000"
    )
    formatted = format_whatsapp_pitch(single_line, candidate_name="Mohamed Hussein", cv_filename="Teaching_CV.pdf")
    paragraphs = formatted.split("\n\n")
    assert len(paragraphs) >= 4, f"Should format into at least 4 distinct paragraphs, got {len(paragraphs)}: {formatted}"
    assert paragraphs[0].startswith("Hello Eraasoft Hiring Team,")
    assert "CS8 Instructor" in paragraphs[1]
    assert "Teaching_CV.pdf" in formatted or "resume" in formatted.lower()
    assert "Mohamed Hussein" in paragraphs[-1]

    # 2. Check bullet preservation
    multi_line = (
        "Hello Hiring Team,\n\n"
        "I'm reaching out regarding the Python Developer role.\n\n"
        "- Built ETL pipelines\n- Optimized database queries\n\n"
        "I have attached my resume (PDF) for your review.\n\n"
        "Best regards,\nCandidate Name"
    )
    formatted_multi = format_whatsapp_pitch(multi_line, candidate_name="Candidate Name")
    assert "• Built ETL pipelines" in formatted_multi
    assert "• Optimized database queries" in formatted_multi
    assert len(formatted_multi.split("\n\n")) >= 4


def test_whatsapp_web_url_encodes_paragraphs():
    """Verify build_whatsapp_web_url encodes multi-paragraph newlines into %0A%0A."""
    text = "Hello Team,\n\nI'm reaching out.\n\nBest regards,\nMe"
    url = build_whatsapp_web_url("201000000000", text)
    assert "https://web.whatsapp.com/send?phone=201000000000&text=" in url
    assert "%0A%0A" in url, "Multi-paragraph newlines should be encoded as %0A%0A in URL query"


def test_api_open_in_edge_endpoint(client):
    """Test /api/whatsapp/open-in-edge endpoint returns success and correct launch payload."""
    from unittest.mock import patch
    with patch("appliers.whatsapp_launcher.open_edge_browser", return_value=True):
        resp = client.post("/api/whatsapp/open-in-edge", json={
            "phone": "201000000000",
            "pitch": "Hello Team,\n\nTest message\n\nBest regards,\nCandidate",
            "cv_path": None
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["launched_via"] == "edge_job_agent"
        assert "web_url" in data
        assert "201000000000" in data["phone"]


def test_launch_whatsapp_web_with_cv():
    """Verify launch_whatsapp_web copies CV to clipboard and opens Edge in job_agent profile."""
    from unittest.mock import patch
    cv_path = get_resume_for_role("Data Analyst")
    if not cv_path or not os.path.exists(cv_path):
        pytest.skip("Configured CV file not found.")

    with patch("appliers.whatsapp_launcher.open_edge_browser", return_value=True):
        res = launch_whatsapp_web(
            phone="201000000000",
            pitch="Test Pitch",
            cv_path=cv_path
        )
        assert res["status"] == "success"
        assert res["cv_copied_to_clipboard"] is True
        assert res["launched_via"] == "edge_job_agent"
        assert res["cv_filename"] == os.path.basename(cv_path)


def test_attach_cv_in_whatsapp_web_mock():
    """Verify _attach_cv_in_whatsapp_web handles document file input and preview send."""
    from unittest.mock import MagicMock
    from appliers.whatsapp_worker import _attach_cv_in_whatsapp_web

    mock_page = MagicMock()
    mock_doc_input = MagicMock()
    # Return document input when query_selector_all is called
    mock_page.query_selector_all.return_value = [mock_doc_input]
    mock_send_btn = MagicMock()
    mock_page.wait_for_selector.return_value = mock_send_btn

    cv_path = get_resume_for_role("Data Analyst")
    if not cv_path or not os.path.exists(cv_path):
        pytest.skip("Configured CV file not found.")

    # Test Autopilot send (click_send=True)
    success = _attach_cv_in_whatsapp_web(mock_page, cv_path, click_send=True)
    assert success is True
    assert mock_doc_input.set_input_files.called
    assert mock_send_btn.click.called

    # Test Copilot review mode (click_send=False)
    mock_doc_input.reset_mock()
    mock_send_btn.reset_mock()
    review_success = _attach_cv_in_whatsapp_web(mock_page, cv_path, click_send=False)
    assert review_success is True
    assert mock_doc_input.set_input_files.called
    assert not mock_send_btn.click.called, "Should leave preview modal open in review mode"


