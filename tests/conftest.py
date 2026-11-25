import os
import json
import sqlite3
import tempfile
from datetime import datetime
import pytest
import core.applicant_profile as ap
import core.database as db
import core.scorer as scorer

# Set temporary test database BEFORE any test modules are imported
_TEST_DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TEST_DB_PATH = _TEST_DB_FILE.name
_TEST_DB_FILE.close()

db.DB_PATH = TEST_DB_PATH
scorer.DB_PATH = TEST_DB_PATH
try:
    import appliers.ats_copilot as ats
    ats.DB_PATH = TEST_DB_PATH
except Exception:
    pass

MOCK_PROFILE = {
    "personal_info": {
        "full_name": "Test Candidate",
        "first_name": "Test",
        "last_name": "Candidate",
        "email": "test.applicant@example.com",
        "phone": "+201000000000",
        "city": "Cairo",
        "country": "Egypt",
        "linkedin_url": "https://linkedin.com/in/applicant",
        "github_url": "https://github.com/applicant",
        "portfolio_url": "https://applicant.dev",
        "resume_base_dir": "",
        "default_resume_path": "Candidate_Resume.pdf"
    },
    "smart_screening": {
        "driving_license": False,
        "military_status": "Exempted / Completed",
        "notice_period_days": 30,
        "home_country": "Egypt",
        "home_city": "Cairo",
        "sponsorship_outside_home_only": True,
        "relocate_outside_home_only": True,
        "expected_salary_egp": 30000,
        "expected_salary_usd": 1500,
        "current_salary": "Negotiable",
        "years_experience_by_role": {
            "Computer Vision & AI": 1,
            "Data Science & Machine Learning": 1,
            "Data Analytics & BI": 1,
            "Teaching & STEM Instructor": 3
        },
        "resumes_by_role": {}
    },
    "auto_apply_settings": {
        "enabled": False,
        "batch_size_per_run": 3,
        "max_runs_per_day": 5,
        "min_relevance_score": 70,
        "channels_enabled": {
            "email": True,
            "whatsapp": True,
            "easy_apply": True,
            "platform": True
        },
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 465,
        "smtp_email": "test.applicant@example.com",
        "smtp_app_password": "",
        "email_signature_path": "",
        "email_signature_personal": "Best regards,\nTest Candidate\ntest.applicant@example.com | +201000000000",
        "whatsapp_mode": "deep_link",
        "whatsapp_default_language": "auto"
    },
    "custom_qa_pairs": {}
}

@pytest.fixture(autouse=True)
def mock_candidate_profile(tmp_path, monkeypatch):
    """
    Decouples all tests from developer's local candidate_profile.json
    by redirecting PROFILE_PATH to a pristine temporary mock profile.
    """
    profile_file = tmp_path / "candidate_profile.json"
    profile_file.write_text(json.dumps(MOCK_PROFILE, indent=2), encoding="utf-8")
    monkeypatch.setattr(ap, "PROFILE_PATH", str(profile_file))
    return MOCK_PROFILE

@pytest.fixture(autouse=True)
def isolate_test_database():
    """
    Decouples all tests from the live production database (output/jobs_state.db)
    by setting up a pristine, fast temporary SQLite database with essential seed jobs.
    """
    db.DB_PATH = TEST_DB_PATH
    scorer.DB_PATH = TEST_DB_PATH
    try:
        import appliers.ats_copilot as ats
        ats.DB_PATH = TEST_DB_PATH
    except Exception:
        pass

    db.init_db()

    # Re-seed representative jobs for copilot, worker, and filter tests
    conn = sqlite3.connect(TEST_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM jobs")
    cursor.executemany(
        """
        INSERT INTO jobs (
            job_id, title, company, location, job_url, relevance_score, status,
            apply_type, apply_channel, is_applied, apply_payload, is_easy_apply, description, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "platform_job_1", "Senior Data Scientist", "Sporty Group", "Cairo, Egypt",
                "https://jobs.lever.co/sporty/platform_job_1", 92.0, "liked",
                "platform", "platform", 0, "{}", 0,
                "Looking for a Senior Data Scientist proficient in Python and SQL with 3+ years experience.",
                datetime.now().isoformat()
            ),
            (
                "email_job_1", "Data Analyst", "Tech Corp", "Cairo, Egypt",
                "https://example.com/job/email1", 88.0, "liked",
                "email", "email", 0,
                json.dumps({
                    "recipient_email": "hr@techcorp.com",
                    "subject_hint": "Data Analyst Application",
                    "generated_email": {
                        "subject": "Data Analyst Application - Test Candidate",
                        "body": "Dear Hiring Team,\n\nI am excited to apply for the Data Analyst position.",
                        "recipient_email": "hr@techcorp.com"
                    }
                }),
                0, "Looking for a Data Analyst with SQL and Python skills.",
                datetime.now().isoformat()
            ),
            (
                "cs8 instructor|eraasoft", "CS8 Instructor", "Eraasoft", "Cairo, Egypt",
                "https://example.com/job/wa1", 85.0, "liked",
                "whatsapp", "whatsapp", 0,
                json.dumps({"phone": "+201000000000"}),
                0, "Looking for Python and AI Instructor.",
                datetime.now().isoformat()
            ),
            (
                "junior data analyst|hire hangar", "Junior Data Analyst", "Hire Hangar", "Cairo, Egypt",
                "https://example.com/job/ea2", 89.0, "liked",
                "easy_apply", "easy_apply", 0, "{}", 1,
                "Junior Data Analyst with SQL and Python skills.",
                datetime.now().isoformat()
            ),
            (
                "easy_apply_job_1", "Software Engineer", "EasyCorp", "Cairo, Egypt",
                "https://linkedin.com/jobs/view/ea1", 89.0, "liked",
                "easy_apply", "easy_apply", 0, "{}", 1,
                "Full Stack Software Engineer with Python and React.",
                datetime.now().isoformat()
            ),
            (
                "pending_job_1", "Junior Python Dev", "StartUp", "Remote",
                "https://example.com/job/p1", 80.0, "pending",
                "manual", "manual", 0, "{}", 0,
                "Junior Backend Developer with FastAPI.",
                datetime.now().isoformat()
            ),
        ]
    )
    conn.commit()
    conn.close()

    yield TEST_DB_PATH

def pytest_sessionfinish(session, exitstatus):
    """Clean up temporary test database on test session end."""
    if os.path.exists(TEST_DB_PATH):
        try:
            os.remove(TEST_DB_PATH)
        except Exception:
            pass

@pytest.fixture(autouse=True)
def isolate_background_and_network_io(monkeypatch):
    """
    Prevents background subprocesses, live API requests, and startup task scheduler syncs
    from stalling unit tests.
    """
    # 1. Prevent Windows Task Scheduler subprocesses and background rescore thread on web startup
    try:
        import web.app as web_app
        monkeypatch.setattr(web_app, "_startup_background_tasks", lambda: None)
        monkeypatch.setattr(web_app, "_last_rescore_date", datetime.now().strftime("%Y-%m-%d"))
    except Exception:
        pass

    try:
        import core.task_scheduler as ts
        monkeypatch.setattr(ts, "sync_autopilot_windows_task", lambda *args, **kwargs: {"status": "skipped"})
    except Exception:
        pass

    # 2. Prevent outbound Google Gemini network calls in tests that don't explicitly mock Gemini
    from unittest.mock import MagicMock
    try:
        import core.gemini_client as gc
        _default_mock_resp = MagicMock()
        _default_mock_resp.text = json.dumps({
            "keywords": ["python", "pytorch", "fastapi", "docker"],
            "body": "Dear Hiring Team,\n\nI am applying for this role.\n\nBest regards"
        })
        monkeypatch.setattr(gc, "generate_content_resilient", lambda *args, **kwargs: (_default_mock_resp, "mock-gemini"))
    except Exception:
        pass

    try:
        import core.role_keywords as rk
        monkeypatch.setattr(rk, "get_gemini_client", lambda *args, **kwargs: None)
        monkeypatch.setattr(rk, "generate_content_resilient", lambda *args, **kwargs: (_default_mock_resp, "mock-gemini"))
    except Exception:
        pass

    try:
        import web.app as web_app
        monkeypatch.setattr(web_app, "analyze_job_and_tune_config", lambda *args, **kwargs: None)
    except Exception:
        pass

    try:
        import core.config_tuner as ct
        monkeypatch.setattr(ct, "analyze_job_and_tune_config", lambda *args, **kwargs: None)
        monkeypatch.setattr(ct, "client", None)
    except Exception:
        pass

    try:
        import appliers.ats_copilot as ats
        monkeypatch.setattr(ats, "gemini_client", None)
    except Exception:
        pass

    try:
        import appliers.whatsapp_copilot as wa_copilot
        monkeypatch.setattr(wa_copilot, "gemini_client", None)
    except Exception:
        pass

    try:
        import appliers.email_generator as eg
        monkeypatch.setattr(eg, "client", MagicMock())
    except Exception:
        pass
