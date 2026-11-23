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

def test_extract_resume_keywords_endpoint(client, tmp_path):
    """Test /api/extract-resume-keywords endpoint extracting skills from resume file."""
    temp_resume = tmp_path / "my_tech_cv.txt"
    temp_resume.write_text("CORE SKILLS:\nLanguages: Python, SQL\nFrameworks: FastAPI, PyTorch, Docker", encoding="utf-8")

    # 1. Valid resume path
    resp = client.post("/api/extract-resume-keywords", json={"resume_path": str(temp_resume)})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert "python" in data["keywords"]
    assert "pytorch" in data["keywords"]
    assert data["count"] == len(data["keywords"])

    # 2. Missing resume_path
    resp_missing = client.post("/api/extract-resume-keywords", json={"resume_path": ""})
    assert resp_missing.status_code == 400

    # 3. Non-existent file path
    resp_404 = client.post("/api/extract-resume-keywords", json={"resume_path": "C:\\fake_cv_non_existent.pdf"})
    assert resp_404.status_code == 404

def test_smart_screening_expected_salary_by_role_model():
    """Verify SmartScreening and CandidateProfile Pydantic models validate expected_salary_by_role."""
    from core.applicant_profile import SmartScreening, CandidateProfile

    screening = SmartScreening(
        expected_salary_egp=35000,
        expected_salary_usd=1500,
        expected_salary_by_role={
            "Computer Vision & AI": {"egp": 45000, "usd": 2000},
            "Teaching & STEM Instructor": {"egp": 25000, "usd": 1000}
        }
    )
    assert screening.expected_salary_by_role["Computer Vision & AI"]["egp"] == 45000
    assert screening.expected_salary_by_role["Teaching & STEM Instructor"]["usd"] == 1000

    profile = CandidateProfile(smart_screening=screening)
    dumped = profile.model_dump()
    assert "expected_salary_by_role" in dumped["smart_screening"]
    assert dumped["smart_screening"]["expected_salary_by_role"]["Computer Vision & AI"]["egp"] == 45000

def test_resolve_expected_salary_for_role():
    """Verify resolve_expected_salary_for_role priority matching and fallbacks."""
    from core.applicant_profile import resolve_expected_salary_for_role

    mock_profile = {
        "smart_screening": {
            "expected_salary_egp": 35000,
            "expected_salary_usd": 1500,
            "expected_salary_by_role": {
                "Computer Vision & AI": {"egp": 50000, "usd": 2200},
                "Data Analytics": {"egp": 30000, "usd": 1200}
            }
        }
    }

    mock_config = {
        "ROLES": [
            {
                "title": "Computer Vision & AI",
                "english_terms": ["CV Engineer", "Vision Researcher"]
            },
            {
                "title": "Data Analytics",
                "english_terms": ["BI Developer", "Tableau Analyst"]
            }
        ]
    }

    # 1. Exact match
    assert resolve_expected_salary_for_role("Computer Vision & AI", "egp", profile=mock_profile) == 50000
    assert resolve_expected_salary_for_role("Computer Vision & AI", "usd", profile=mock_profile) == 2200

    # 2. Substring match
    assert resolve_expected_salary_for_role("Lead Data Analytics Specialist", "egp", profile=mock_profile) == 30000

    # 3. Config terms match
    assert resolve_expected_salary_for_role("Junior CV Engineer", "egp", profile=mock_profile, config=mock_config) == 50000

    # 4. Fallback for unconfigured role
    assert resolve_expected_salary_for_role("Unknown Generalist", "egp", profile=mock_profile) == 35000
    assert resolve_expected_salary_for_role("Unknown Generalist", "usd", profile=mock_profile) == 1500

def test_screening_resolver_role_specific_salary():
    """Verify ScreeningResolver incorporates role-specific salary for target role applications."""
    from appliers.screening_resolver import ScreeningResolver

    profile = load_profile()
    orig_screening = dict(profile.get("smart_screening", {}))
    try:
        profile["smart_screening"]["expected_salary_egp"] = 35000
        profile["smart_screening"]["expected_salary_usd"] = 1500
        profile["smart_screening"]["expected_salary_by_role"] = {
            "AI Engineer": {"egp": 60000, "usd": 2500},
            "STEM Instructor": {"egp": 25000, "usd": 1000}
        }
        save_profile(profile)

        # AI Engineer application
        resolver_ai = ScreeningResolver(job_title="Senior AI Engineer", job_location="Cairo, Egypt")
        ai_egp = resolver_ai.resolve_field_value("What is your expected monthly salary in EGP?", field_type="number")
        assert ai_egp == 60000

        ai_usd = resolver_ai.resolve_field_value("Expected compensation USD", field_type="number")
        assert ai_usd == 2500

        # STEM Instructor application
        resolver_inst = ScreeningResolver(job_title="STEM Instructor", job_location="Cairo, Egypt")
        inst_egp = resolver_inst.resolve_field_value("Expected salary", field_type="number")
        assert inst_egp == 25000

        # General unconfigured role falls back to global expected salary
        resolver_gen = ScreeningResolver(job_title="Office Admin", job_location="Cairo, Egypt")
        gen_egp = resolver_gen.resolve_field_value("Salary expectation", field_type="number")
        assert gen_egp == 35000
    finally:
        profile["smart_screening"] = orig_screening
        save_profile(profile)

def test_scorer_salary_bounds_check():
    """Verify core/scorer.py rewards jobs meeting expected salary and penalizes jobs below."""
    from core.scorer import calculate_score, extract_salary_bounds

    # 1. extract_salary_bounds parsing test
    sal1 = extract_salary_bounds({"salary": "40,000 - 50,000 EGP"})
    assert sal1 == (40000.0, 50000.0, "egp")

    sal2 = extract_salary_bounds({"salary": "$1,500 - $2,500 / month"})
    assert sal2 == (1500.0, 2500.0, "usd")

    sal3 = extract_salary_bounds({"description": "Competitive package: 45k - 60k egp with full benefits"})
    assert sal3 == (45000.0, 60000.0, "egp")

    # 2. Score boost / penalty test
    config = {
        "ROLES": [
            {
                "title": "AI Engineer",
                "english_terms": ["AI Engineer", "Machine Learning"],
                "years_experience": 2,
                "expected_salary": {"egp": 40000, "usd": 2000}
            }
        ],
        "TARGET_LOCATIONS": ["Cairo", "Remote"]
    }

    base_job = {
        "title": "AI Engineer",
        "description": "Python, PyTorch, Deep Learning pipelines in Cairo",
        "company": "TechCorp",
        "location": "Cairo",
        "job_type": "Full-time"
    }

    # Job meeting compensation expectations
    good_job = dict(base_job, salary="45,000 - 55,000 EGP")
    # Job paying significantly below expected compensation (e.g. 15k vs 40k expected)
    low_job = dict(base_job, salary="12,000 - 18,000 EGP")

    neutral_score = calculate_score(base_job, config=config, apply_date_penalty=False)
    good_score = calculate_score(good_job, config=config, apply_date_penalty=False)
    low_score = calculate_score(low_job, config=config, apply_date_penalty=False)

    assert good_score > neutral_score
    assert low_score < neutral_score

def test_api_profile_expected_salary_by_role_persistence(client):
    """Verify /api/profile saves and returns expected_salary_by_role."""
    orig_profile = client.get("/api/profile").json()
    try:
        updated_data = dict(orig_profile)
        if "smart_screening" not in updated_data:
            updated_data["smart_screening"] = {}
        updated_data["smart_screening"]["expected_salary_by_role"] = {
            "Computer Vision & AI": {"egp": 48000, "usd": 2100},
            "Data Science & Machine Learning": {"egp": 42000, "usd": 1800}
        }

        save_resp = client.post("/api/profile", json=updated_data)
        assert save_resp.status_code == 200
        saved_body = save_resp.json()
        assert saved_body["status"] == "success"
        assert saved_body["profile"]["smart_screening"]["expected_salary_by_role"]["Computer Vision & AI"]["egp"] == 48000

        # Verify round-trip GET
        get_resp = client.get("/api/profile")
        assert get_resp.status_code == 200
        fetched = get_resp.json()
        assert fetched["smart_screening"]["expected_salary_by_role"]["Computer Vision & AI"]["egp"] == 48000
        assert fetched["smart_screening"]["expected_salary_by_role"]["Data Science & Machine Learning"]["usd"] == 1800
    finally:
        client.post("/api/profile", json=orig_profile)


