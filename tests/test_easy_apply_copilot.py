import os
import sys
import json
import sqlite3
import pytest
from fastapi.testclient import TestClient

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from web.app import app
from core.database import DB_PATH
from core.applicant_profile import get_resume_for_role
from appliers.screening_resolver import ScreeningResolver
from appliers.easy_apply_copilot import prepare_easy_apply, get_session, EasyApplySession, ACTIVE_SESSIONS


@pytest.fixture
def client():
    return TestClient(app)


def test_screening_resolver_contact_fields():
    """Verify screening resolver correctly extracts candidate contact details."""
    resolver = ScreeningResolver(job_title="Data Analyst", job_location="Cairo, Egypt")

    assert resolver.resolve_field_value("First Name") == "Mohamed"
    assert resolver.resolve_field_value("Last Name") == "Hussein"
    assert resolver.resolve_field_value("Full Name") == "Mohamed Hussein"
    assert "mhmd7syn" in resolver.resolve_field_value("Email Address")
    assert "10" in resolver.resolve_field_value("Phone Number")
    assert resolver.resolve_field_value("City") == "Cairo"
    assert resolver.resolve_field_value("Country") == "Egypt"
    assert "linkedin.com" in resolver.resolve_field_value("LinkedIn URL")


def test_screening_resolver_contextual_sponsorship():
    """Verify context-aware visa sponsorship and relocation rules."""
    # Home Country Job (Cairo, Egypt) -> No sponsorship needed
    res_home = ScreeningResolver(job_title="Data Analyst", job_location="Cairo, Egypt")
    ans_sponsor_home = res_home.resolve_field_value("Will you now or in the future require visa sponsorship?")
    assert ans_sponsor_home == "No"

    # Abroad Job (London, UK) -> Sponsorship needed
    res_abroad = ScreeningResolver(job_title="Data Analyst", job_location="London, United Kingdom")
    ans_sponsor_abroad = res_abroad.resolve_field_value("Will you now or in the future require visa sponsorship?")
    assert ans_sponsor_abroad == "Yes"

    # Relocation outside home city
    ans_reloc = res_abroad.resolve_field_value("Are you willing to relocate?")
    assert ans_reloc == "Yes"


def test_screening_resolver_experience_and_legal():
    """Verify legal, military, driving, notice period, and experience resolution."""
    res = ScreeningResolver(job_title="CS8 Instructor", job_location="Cairo, Egypt")

    assert res.resolve_field_value("Do you have a valid driving license?") == "No"
    assert "Exempted" in res.resolve_field_value("Military Status")
    assert res.resolve_field_value("Notice Period (in days)", field_type="number") == 30

    # Teaching experience: 3 years configured in profile
    assert res.resolve_field_value("How many years of teaching experience do you have?", field_type="number") == 3


def test_cv_resolution_for_easy_apply_roles():
    """Verify that Easy Apply job titles resolve to real role CV PDFs in OneDrive."""
    cv_analyst = get_resume_for_role("Junior Data Analyst")
    assert cv_analyst is not None
    assert os.path.exists(cv_analyst)
    assert "Data Analytics & BI" in cv_analyst

    cv_instructor = get_resume_for_role("AI Facilitator/Instructor")
    assert cv_instructor is not None
    assert os.path.exists(cv_instructor)
    assert "Teaching & STEM Instructor" in cv_instructor


def test_api_prepare_easy_apply_endpoint(client):
    """Test /api/easy-apply/prepare endpoint returns complete pre-fill context."""
    response = client.post("/api/easy-apply/prepare", json={"job_id": "junior data analyst|hire hangar"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["title"] == "Junior Data Analyst"
    assert data["attached_cv"]["exists"] is True
    assert data["attached_cv"]["filename"] == "Mohamed_Hussein_CV.pdf"
    assert data["contact_preview"]["full_name"] == "Mohamed Hussein"
    assert data["screening_preview"]["requires_sponsorship"] is False


def test_api_easy_apply_status_endpoint(client):
    """Test /api/easy-apply/status endpoint with idle and active sessions."""
    # Non-existent session
    idle_resp = client.get("/api/easy-apply/status/nonexistent_job")
    assert idle_resp.status_code == 200
    assert idle_resp.json()["status"] == "idle"

    # Manually register mock session
    test_id = "test_ea_session_123"
    mock_session = EasyApplySession(
        job_id=test_id,
        job_url="https://example.com/apply",
        title="Test Analyst",
        company="Acme Corp",
        site="glassdoor",
        cv_path="C:\\test\\cv.pdf"
    )
    mock_session.status = "paused_for_review"
    mock_session.current_step = "Paused at final Review step!"
    mock_session.log("Pre-fill complete.")
    ACTIVE_SESSIONS[test_id] = mock_session

    active_resp = client.get(f"/api/easy-apply/status/{test_id}")
    assert active_resp.status_code == 200
    session_data = active_resp.json()
    assert session_data["status"] == "paused_for_review"
    assert "Paused at final" in session_data["current_step"]
    assert len(session_data["logs"]) > 0

    # Cleanup mock
    ACTIVE_SESSIONS.pop(test_id, None)


def test_decoupled_easy_apply_workflow(client):
    """Verify that preparing or running an assisted session does NOT mark applied until explicit confirmation."""
    test_job_id = "junior data analyst|hire hangar"

    # Check initial state
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT is_applied, apply_status FROM jobs WHERE job_id = ?", (test_job_id,))
    row = cursor.fetchone()
    initial_applied = row[0] if row else 0

    # Reset to unapplied
    cursor.execute("UPDATE jobs SET is_applied = 0, apply_status = 'unapplied' WHERE job_id = ?", (test_job_id,))
    conn.commit()
    conn.close()

    # Call prepare endpoint: must NOT mark applied
    prep_resp = client.post("/api/easy-apply/prepare", json={"job_id": test_job_id})
    assert prep_resp.status_code == 200

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT is_applied FROM jobs WHERE job_id = ?", (test_job_id,))
    row = cursor.fetchone()
    conn.close()
    assert row[0] == 0, "Preparing Easy Apply must NOT mark job applied in DB!"

    # Call explicit mark-applied endpoint
    mark_resp = client.post("/api/easy-apply/mark-applied", json={"job_id": test_job_id})
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
    assert "sent_easy_apply" in payload

    # Restore initial state
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE jobs SET is_applied = ?, apply_status = ? WHERE job_id = ?", (initial_applied, "applied" if initial_applied else "unapplied", test_job_id))
    conn.commit()
    conn.close()
