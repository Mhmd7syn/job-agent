import os
import json
import tempfile
import pytest
from fastapi.testclient import TestClient

from web.app import app
import core.config as app_config
from core.applicant_profile import get_resume_for_role, load_profile, save_profile

@pytest.fixture
def client():
    return TestClient(app)

def test_get_resume_for_role_from_settings(monkeypatch, tmp_path):
    """Verify that get_resume_for_role returns the resume explicitly configured in settings."""
    # Create two dummy resume files
    cv1 = tmp_path / "resume_ai.pdf"
    cv1.write_text("dummy resume content AI")
    cv2 = tmp_path / "resume_devops.pdf"
    cv2.write_text("dummy resume content DevOps")

    mock_roles = [
        {
            "title": "Machine Learning Specialist",
            "years_experience": 1,
            "english_terms": ["Machine Learning Engineer", "AI Researcher"],
            "resume_path": str(cv1)
        },
        {
            "title": "Cloud DevOps Engineer",
            "years_experience": 2,
            "english_terms": ["DevOps", "Site Reliability Engineer", "Kubernetes"],
            "resume_path": str(cv2)
        }
    ]

    monkeypatch.setattr(app_config, "ROLES", mock_roles)

    # 1. Exact title match
    res1 = get_resume_for_role("Machine Learning Specialist")
    assert res1 == str(cv1)

    # 2. Search terms match from settings
    res2 = get_resume_for_role("Senior Kubernetes Platform Engineer")
    assert res2 == str(cv2)

    res3 = get_resume_for_role("AI Researcher & Deep Learning")
    assert res3 == str(cv1)

def test_custom_role_with_explicit_resume(monkeypatch, tmp_path):
    """Verify that any custom role created by the user resolves to its explicit resume."""
    custom_cv = tmp_path / "custom_cybersec.pdf"
    custom_cv.write_text("cybersec cv")

    mock_roles = [
        {
            "title": "Cybersecurity Analyst",
            "years_experience": 3,
            "english_terms": ["SOC Analyst", "Security Engineer"],
            "resume_path": str(custom_cv)
        }
    ]
    monkeypatch.setattr(app_config, "ROLES", mock_roles)

    matched = get_resume_for_role("SOC Analyst - Night Shift")
    assert matched == str(custom_cv)

def test_fallback_to_default_resume_when_no_match(monkeypatch, tmp_path):
    """Verify fallback behavior when an unknown job title is queried."""
    fallback_cv = tmp_path / "general_fallback.pdf"
    fallback_cv.write_text("general resume")

    # Profile with default_resume_path
    profile = load_profile()
    orig_personal = dict(profile.get("personal_info", {}))
    try:
        profile["personal_info"]["default_resume_path"] = str(fallback_cv)
        save_profile(profile)

        mock_roles = [
            {
                "title": "Mobile App Developer",
                "years_experience": 1,
                "english_terms": ["Flutter Developer", "iOS Engineer"],
                "resume_path": ""
            }
        ]
        monkeypatch.setattr(app_config, "ROLES", mock_roles)

        # Query completely unrelated title
        res = get_resume_for_role("Accountant / Finance Manager")
        assert res == str(fallback_cv)
    finally:
        profile["personal_info"] = orig_personal
        save_profile(profile)

def test_upload_role_resume_endpoint(client, tmp_path):
    """Test /api/upload-role-resume endpoint saves the resume file and returns its path."""
    content = b"%PDF-1.4 simulated resume content"
    files = {"file": ("my_test_resume.pdf", content, "application/pdf")}
    response = client.post("/api/upload-role-resume", files=files)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["filename"] == "my_test_resume.pdf"
    assert os.path.exists(data["file_path"])

def test_check_resume_file_endpoint(client, tmp_path):
    """Test /api/check-resume-file returns correct existence and metadata."""
    temp_file = tmp_path / "valid_resume.pdf"
    temp_file.write_text("PDF content check")

    # Check existing file
    resp_exists = client.post("/api/check-resume-file", json={"path": str(temp_file)})
    assert resp_exists.status_code == 200
    assert resp_exists.json()["exists"] is True
    assert resp_exists.json()["filename"] == "valid_resume.pdf"

    # Check non-existent file
    resp_missing = client.post("/api/check-resume-file", json={"path": "C:\\fake_path_12345.pdf"})
    assert resp_missing.status_code == 200
    assert resp_missing.json()["exists"] is False
