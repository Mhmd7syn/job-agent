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
    build_whatsapp_desktop_url,
    build_wa_me_url,
    build_whatsapp_web_url,
    generate_fallback_pitch,
    generate_whatsapp_pitch
)
from appliers.whatsapp_launcher import launch_whatsapp_desktop, launch_whatsapp_web


@pytest.fixture
def client():
    return TestClient(app)


def test_phone_normalization():
    """Verify phone normalization for Egyptian, Gulf, and international formats."""
    assert normalize_phone_number("01097748566") == "201097748566"
    assert normalize_phone_number("+20 10 9774 8566") == "201097748566"
    assert normalize_phone_number("00201112881552") == "201112881552"
    assert normalize_phone_number("01112881552") == "201112881552"
    assert normalize_phone_number("01551234567") == "201551234567"
    assert normalize_phone_number("01221234567") == "201221234567"
    assert normalize_phone_number("0501234567") in ("966501234567", "971501234567")
    assert normalize_phone_number("+966 50 123 4567") == "966501234567"


def test_url_builders():
    """Verify protocol URL formats for WhatsApp Desktop, wa.me, and WhatsApp Web."""
    desktop_url = build_whatsapp_desktop_url("201097748566", "Hello from Mohamed")
    assert desktop_url.startswith("whatsapp://send?phone=201097748566&text=")
    assert "Hello%20from%20Mohamed" in desktop_url

    wa_me_url = build_wa_me_url("201097748566", "Hello from Mohamed")
    assert wa_me_url.startswith("https://wa.me/201097748566?text=")
    assert "Hello%20from%20Mohamed" in wa_me_url

    web_url = build_whatsapp_web_url("201097748566", "Hello from Mohamed")
    assert web_url.startswith("https://web.whatsapp.com/send?phone=201097748566&text=")


def test_fallback_pitch_generation():
    """Verify fallback pitch creates clean, professional English text with candidate details."""
    pitch_data = generate_fallback_pitch(
        job_title="Data Analyst",
        company="Retail Corp",
        candidate_name="Mohamed Hussein",
        cv_path=None,
        candidate_phone="+201097344958",
        candidate_email="mhmd7syn.contact@gmail.com",
        linkedin_url="https://linkedin.com/in/Mhmd7syn"
    )
    assert pitch_data["status"] == "success"
    pitch_text = pitch_data["pitch"]
    assert "Data Analyst" in pitch_text
    assert "Retail Corp" in pitch_text
    assert "Mohamed Hussein" in pitch_text
    assert "resume" in pitch_text.lower() or "cv" in pitch_text.lower()
    assert "+201097344958" in pitch_text
    assert "linkedin.com/in/Mhmd7syn" in pitch_text


def test_cv_resolution_for_whatsapp_roles():
    """Verify that roles corresponding to WhatsApp postings resolve to real CV PDFs in OneDrive."""
    cv_teaching = get_resume_for_role("CS8 Instructor")
    assert cv_teaching is not None
    assert os.path.exists(cv_teaching)
    assert "Teaching & STEM Instructor" in cv_teaching

    cv_analytics = get_resume_for_role("Data Analyst")
    assert cv_analytics is not None
    assert os.path.exists(cv_analytics)
    assert "Data Analytics & BI" in cv_analytics


def test_api_generate_pitch_endpoint(client):
    """Test /api/whatsapp/generate-pitch returns structured pitch with real CV path."""
    response = client.post("/api/whatsapp/generate-pitch", json={"job_id": "cs8 instructor|eraasoft"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "phone" in data
    assert data["phone"] == "201097748566"
    assert "pitch" in data
    assert len(data["pitch"]) > 20
    assert "attached_cv" in data
    expected_cv = get_resume_for_role("Teaching & STEM Instructor")
    if expected_cv:
        assert data["attached_cv"]["filename"] == os.path.basename(expected_cv)
    else:
        assert data["attached_cv"]["filename"] in ["Mohamed_Hussein_CV.pdf", "MohamedHussein_ComputerScienceInstructor_Resume.pdf"]
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
        "phone": "201097748566",
        "pitch": "Test pitch message",
        "applied_via": "whatsapp_desktop"
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
    assert payload["sent_whatsapp"]["phone"] == "201097748566"

    # Restore initial state
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE jobs SET is_applied = ?, apply_status = ? WHERE job_id = ?", (initial_applied, "applied" if initial_applied else "unapplied", test_job_id))
    conn.commit()
    conn.close()
