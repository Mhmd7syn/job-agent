import os
import sys
import tempfile
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import core.database as db
from web.app import app

client = TestClient(app)


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_db_path = f.name
    orig_db = db.DB_PATH
    db.DB_PATH = temp_db_path
    db.init_db()
    yield temp_db_path
    db.DB_PATH = orig_db
    if os.path.exists(temp_db_path):
        os.remove(temp_db_path)


def test_save_or_update_job_persists_applied_metadata(temp_db):
    """Verify that save_or_update_job correctly saves and updates applied_at, apply_channel, and apply_status."""
    job_data = {
        "job_id": "job_manual_applied_1",
        "title": "Software Engineer",
        "company": "TechCorp",
        "location": "Cairo",
        "job_url": "https://example.com/job1",
        "status": "liked",
        "is_applied": 1,
        "applied_at": "2026-11-15T10:00:00",
        "apply_channel": "email",
        "apply_status": "applied",
        "relevance_score": 85
    }

    saved, is_new = db.save_or_update_job(job_data, force_pending=False)
    assert is_new is True
    assert saved["status"] == "liked"
    assert saved["is_applied"] == 1
    assert saved["applied_at"] == "2026-11-15T10:00:00"
    assert saved["apply_channel"] == "email"
    assert saved["apply_status"] == "applied"

    # Update existing job with new applied metadata
    update_data = {
        "job_id": "job_manual_applied_1",
        "title": "Senior Software Engineer",
        "company": "TechCorp",
        "location": "Remote",
        "job_url": "https://example.com/job1",
        "is_applied": 1,
        "applied_at": "2026-11-18",
        "apply_channel": "external_portal",
        "apply_status": "applied"
    }
    updated, is_new_update = db.save_or_update_job(update_data, force_pending=False)
    assert is_new_update is False
    assert updated["title"] == "Senior Software Engineer"
    assert updated["is_applied"] == 1
    assert updated["applied_at"] == "2026-11-18"
    assert updated["apply_channel"] == "external_portal"
    assert updated["apply_status"] == "applied"


def test_add_manual_job_default_pending(temp_db):
    """Verify adding manual job with default status sets status=pending and is_applied=0."""
    fake_job = {
        "job_id": "fake_pending_job",
        "title": "Data Analyst",
        "company": "DataCorp",
        "job_url": "https://example.com/job-pending",
        "relevance_score": 90,
        "description": "SQL and Python"
    }

    with patch("web.app.scrape_job_from_url", return_value=fake_job):
        res = client.post("/api/jobs/add-by-url", json={
            "url": "https://example.com/job-pending",
            "status": "pending"
        })
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        job = data["job"]
        assert job["status"] == "pending"
        assert job["is_applied"] == 0
        assert job["apply_status"] == "unapplied"


def test_add_manual_job_status_liked(temp_db):
    """Verify adding manual job with status=liked sets status=liked and is_applied=0."""
    fake_job = {
        "job_id": "fake_liked_job",
        "title": "Machine Learning Engineer",
        "company": "AICorp",
        "job_url": "https://example.com/job-liked",
        "relevance_score": 95,
        "description": "PyTorch and NLP"
    }

    with patch("web.app.scrape_job_from_url", return_value=fake_job):
        res = client.post("/api/jobs/add-by-url", json={
            "url": "https://example.com/job-liked",
            "status": "liked"
        })
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        job = data["job"]
        assert job["status"] == "liked"
        assert job["is_applied"] == 0
        assert job["apply_status"] == "unapplied"


def test_add_manual_job_status_applied_with_date_and_method(temp_db):
    """Verify adding manual job with status=applied sets is_applied=1, applied_at, and apply_channel."""
    fake_job = {
        "job_id": "fake_applied_job",
        "title": "Frontend Engineer",
        "company": "WebCorp",
        "job_url": "https://example.com/job-applied",
        "relevance_score": 88,
        "description": "React and TypeScript"
    }

    with patch("web.app.scrape_job_from_url", return_value=fake_job):
        res = client.post("/api/jobs/add-by-url", json={
            "url": "https://example.com/job-applied",
            "status": "applied",
            "applied_date": "2026-11-12",
            "apply_method": "email"
        })
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        job = data["job"]
        assert job["status"] == "liked"
        assert job["is_applied"] == 1
        assert job["apply_status"] == "applied"
        assert job["applied_at"] == "2026-11-12"
        assert job["apply_channel"] == "email"


def test_add_manual_job_status_applied_external_portal_default_date(temp_db):
    """Verify adding manual job with status=applied and method=external_portal generates default date."""
    fake_job = {
        "job_id": "fake_portal_job",
        "title": "DevOps Engineer",
        "company": "CloudCorp",
        "job_url": "https://example.com/job-portal",
        "relevance_score": 82,
        "description": "Kubernetes and Docker"
    }

    with patch("web.app.scrape_job_from_url", return_value=fake_job):
        res = client.post("/api/jobs/add-by-url", json={
            "url": "https://example.com/job-portal",
            "status": "applied",
            "apply_method": "external_portal"
        })
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        job = data["job"]
        assert job["status"] == "liked"
        assert job["is_applied"] == 1
        assert job["apply_status"] == "applied"
        assert bool(job["applied_at"]) is True
        assert job["apply_channel"] == "external_portal"
