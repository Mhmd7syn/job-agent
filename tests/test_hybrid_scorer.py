import os
from datetime import date
import pytest
from core.scorer import calculate_score, is_valid_job
from core.role_keywords import clear_keyword_cache

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CV_PATH = os.path.join(BASE_DIR, "data", "resumes", "MohamedHussein_ComputerVisionEngineer_Resume.pdf")
INSTRUCTOR_PATH = os.path.join(BASE_DIR, "data", "resumes", "MohamedHussein_ComputerScienceInstructor_Resume.pdf")
DA_PATH = os.path.join(BASE_DIR, "data", "resumes", "MohamedHussein_DataAnalyst_Resume.pdf")

@pytest.fixture(autouse=True)
def clean_cache():
    clear_keyword_cache()
    yield
    clear_keyword_cache()

def test_synonym_matching():
    # Test that synonyms (gcp / google cloud, rest api / restful api) are properly matched and deduplicated
    cfg = {
        "ROLES": [{
            "title": "Cloud / Backend Engineer",
            "english_terms": ["Backend Engineer", "Cloud Engineer"]
        }],
        "RESUME_KEYWORDS": ["google cloud", "gcp", "rest api", "python"],
        "TARGET_LOCATIONS": ["cairo"],
        "TARGET_LEVELS": ["Junior"],
        "LEVEL_EXCLUDE": ["Senior / Lead"]
    }

    job_with_synonyms = {
        "job_id": "job_syn_1",
        "title": "Junior Backend Engineer",
        "company": "CloudTech",
        "location": "Cairo",
        "date_posted": date.today().isoformat(),
        "description": "Looking for GCP and Google Cloud Platform experience with RESTful API development in Python.",
        "job_type": "Full Time"
    }
    score = calculate_score(job_with_synonyms, cfg, apply_date_penalty=False)
    # Role match (+20) + Target level (+15) + Location (+5)
    # Plus tech skills: python (+3), google cloud/gcp (canonical once: +3), rest api/restful api (canonical once: +3) = +9
    # Total = 20 + 15 + 5 + 9 = 49
    assert score == 49


def test_plural_and_inflection_normalization():
    cfg = {
        "ROLES": [{
            "title": "Data Engineer",
            "english_terms": ["Data Engineer"]
        }],
        "RESUME_KEYWORDS": ["database", "python", "pipeline"],
        "TARGET_LOCATIONS": ["cairo"],
        "TARGET_LEVELS": ["Junior"],
        "LEVEL_EXCLUDE": []
    }

    # Job description uses plurals: 'databases', 'pipelines'
    job_plurals = {
        "job_id": "job_plurals_1",
        "title": "Data Engineer",
        "company": "DataCorp",
        "location": "Cairo",
        "date_posted": date.today().isoformat(),
        "description": "Experience building data pipelines and managing relational databases using Python.",
        "job_type": "Full Time"
    }
    score = calculate_score(job_plurals, cfg, apply_date_penalty=False)
    # Tech score should match 'databases' -> 'database' and 'pipelines' -> 'pipeline'
    assert score > 30


def test_role_scoped_scoring():
    cfg = {
        "ROLES": [
            {
                "title": "Computer Vision & AI",
                "english_terms": ["Computer Vision Engineer", "AI Engineer"],
                "resume_path": CV_PATH
            },
            {
                "title": "Teaching & STEM Instructor",
                "english_terms": ["Programming Instructor", "Robotics Instructor", "STEM Instructor"],
                "resume_path": INSTRUCTOR_PATH
            }
        ],
        "TARGET_LOCATIONS": ["cairo"],
        "TARGET_LEVELS": ["Junior", "Fresh Graduate / Entry-level"],
        "LEVEL_EXCLUDE": ["Senior / Lead"]
    }

    # 1. Computer Vision job
    cv_job = {
        "job_id": "job_cv_1",
        "title": "Junior Computer Vision Engineer",
        "company": "VisionTech",
        "location": "Cairo",
        "date_posted": date.today().isoformat(),
        "description": "We are seeking a Computer Vision Engineer with PyTorch, OpenCV, and YOLO object detection skills.",
        "job_type": "Full Time"
    }
    cv_score = calculate_score(cv_job, cfg, apply_date_penalty=False)
    assert cv_score > 40

    # 2. Teaching job
    teaching_job = {
        "job_id": "job_teach_1",
        "title": "Junior Programming Instructor",
        "company": "EduTech",
        "location": "Cairo",
        "date_posted": date.today().isoformat(),
        "description": "Looking for a Programming Instructor with Curriculum Design, Scratch, and Python teaching skills.",
        "job_type": "Full Time"
    }
    teaching_score = calculate_score(teaching_job, cfg, apply_date_penalty=False)
    assert teaching_score > 40


def test_non_tech_role_disqualification():
    cfg = {
        "ROLES": [
            {
                "title": "Computer Vision & AI",
                "english_terms": ["Computer Vision Engineer"],
                "resume_path": CV_PATH
            }
        ],
        "TARGET_LOCATIONS": ["cairo"],
        "TARGET_LEVELS": ["Junior"]
    }

    # Non-technical job (Accounting / Finance)
    accounting_job = {
        "job_id": "job_acc_1",
        "title": "Junior Accountant",
        "company": "Finance Corp",
        "location": "Cairo",
        "date_posted": date.today().isoformat(),
        "description": "Managing balance sheets, payroll records, and financial statements.",
        "job_type": "Full Time"
    }
    assert calculate_score(accounting_job, cfg, apply_date_penalty=False) == 0
    assert not is_valid_job(accounting_job, config=cfg)
