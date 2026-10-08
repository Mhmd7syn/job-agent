import os
import sqlite3
import pytest
from fastapi.testclient import TestClient

from web.app import app
from appliers.ats_copilot import (
    detect_platform,
    generate_ats_cover_letter,
    prepare_ats_application,
    get_job_by_id,
    mark_ats_applied
)
from core.database import DB_PATH

client = TestClient(app)


def test_platform_detection():
    """Verifies that URLs are correctly mapped to their ATS or Web Form vendor."""
    # Greenhouse
    res_gh = detect_platform("https://job-boards.eu.greenhouse.io/sportygroup/jobs/4911824101")
    assert res_gh["platform_key"] == "greenhouse"
    assert res_gh["name"] == "Greenhouse"

    # Lever
    res_lever = detect_platform("https://jobs.lever.co/example-company/12345")
    assert res_lever["platform_key"] == "lever"
    assert res_lever["name"] == "Lever"

    # Workable
    res_workable = detect_platform("https://apply.workable.com/tech-corp/j/ABC123/")
    assert res_workable["platform_key"] == "workable"
    assert res_workable["name"] == "Workable"

    # Recruitee
    res_recruitee = detect_platform("https://siwaresystems.recruitee.com/o/ai-data-science-intern")
    assert res_recruitee["platform_key"] == "recruitee"
    assert res_recruitee["name"] == "Recruitee"

    # Ashby
    res_ashby = detect_platform("https://jobs.ashbyhq.com/scale-ai/456")
    assert res_ashby["platform_key"] == "ashby"
    assert res_ashby["name"] == "Ashby"

    # Workday
    res_wd = detect_platform("https://pwc.wd3.myworkdayjobs.com/Global_Experienced_Careers/job/Cairo/Associate")
    assert res_wd["platform_key"] == "workday"
    assert res_wd["name"] == "Workday"

    # Google Forms
    res_gf = detect_platform("https://docs.google.com/forms/d/e/1FAIpQLSc.../viewform")
    assert res_gf["platform_key"] == "google_forms"
    assert res_gf["name"] == "Google Forms"

    # Typeform
    res_tf = detect_platform("https://company.typeform.com/to/abcxyz")
    assert res_tf["platform_key"] == "typeform"
    assert res_tf["name"] == "Typeform"

    # Universal fallback
    res_univ = detect_platform("https://careers.somecompany.com/apply")
    assert res_univ["platform_key"] == "universal"
    assert res_univ["name"] == "Company ATS Portal"


def test_cover_letter_generation():
    """Verifies that tailored cover letters contain candidate credentials, role context, and personal signature."""
    cl = generate_ats_cover_letter(
        job_title="Data Scientist",
        company="Sporty Group",
        location="Cairo, Egypt",
        job_description="Looking for a Data Scientist proficient in Python and SQL."
    )
    assert "Data Scientist" in cl
    assert "Sporty Group" in cl
    assert "Mohamed Hussein" in cl
    assert "mhmd7syn" in cl or "mohamedh" in cl
    assert len(cl) > 150


def test_api_prepare_ats_endpoint():
    """Tests the /api/ats/prepare endpoint with a real platform job from the database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT job_id FROM jobs WHERE apply_type = 'platform' LIMIT 1")
    row = cursor.fetchone()
    conn.close()

    assert row is not None, "At least one platform job must exist in database"
    job_id = row[0]

    response = client.post("/api/ats/prepare", json={"job_id": job_id})
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "success"
    assert data["job_id"] == job_id
    assert "platform_meta" in data
    assert "attached_cv" in data
    assert data["attached_cv"]["filename"] is not None
    assert "quick_copy" in data
    assert data["quick_copy"]["full_name"] == "Mohamed Hussein"
    assert "expected_salary_egp" in data["quick_copy"]
    assert "cover_letter" in data
    assert len(data["cover_letter"]) > 100


def test_api_ats_status_endpoint():
    """Tests /api/ats/status/{job_id} returns an idle state for an unstarted session."""
    response = client.get("/api/ats/status/test_nonexistent_session")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "idle"
    assert data["current_step"] == "Not started"


def test_decoupled_ats_workflow():
    """
    CRITICAL CO-PILOT RULE:
    Preparing or launching an ATS application must NEVER mark the job as applied.
    The database record remains unapplied until /api/ats/mark-applied is explicitly invoked.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT job_id, is_applied, apply_status FROM jobs WHERE apply_type = 'platform' LIMIT 1")
    row = cursor.fetchone()
    conn.close()

    assert row is not None
    job_id, orig_applied, orig_status = row

    try:
        # 1. Reset job to unapplied state for test
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE jobs SET is_applied = 0, apply_status = 'pending' WHERE job_id = ?", (job_id,))
        conn.commit()
        conn.close()

        # 2. Call /api/ats/prepare
        prep_res = client.post("/api/ats/prepare", json={"job_id": job_id})
        assert prep_res.status_code == 200

        # Verify job is STILL unapplied
        job_after_prep = get_job_by_id(job_id)
        assert job_after_prep["is_applied"] == 0
        assert job_after_prep["apply_status"] == "pending"

        # 3. Explicitly call mark-applied
        apply_res = client.post("/api/ats/mark-applied", json={"job_id": job_id})
        assert apply_res.status_code == 200
        assert apply_res.json()["status"] == "success"

        # Verify job is now applied
        job_after_apply = get_job_by_id(job_id)
        assert job_after_apply["is_applied"] == 1
        assert job_after_apply["apply_status"] == "applied"
        assert job_after_apply["applied_at"] is not None

    finally:
        # Restore original state
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE jobs SET is_applied = ?, apply_status = ? WHERE job_id = ?",
            (orig_applied, orig_status, job_id)
        )
        conn.commit()
        conn.close()
