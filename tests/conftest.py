import os
import json
import pytest
import core.applicant_profile as ap

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
