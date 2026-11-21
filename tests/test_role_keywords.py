import os
import time
import pytest
from core.role_keywords import (
    extract_skills_from_resume_text,
    get_resume_keywords_for_role,
    get_all_role_keywords,
    get_unified_resume_keywords,
    clear_keyword_cache,
    _RESUME_SKILL_CACHE
)
from core.cv_parser import extract_text_from_file

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CV_PATH = os.path.join(BASE_DIR, "data", "resumes", "MohamedHussein_ComputerVisionEngineer_Resume.pdf")
DS_PATH = os.path.join(BASE_DIR, "data", "resumes", "MohamedHussein_DataScientist_Resume.pdf")
DA_PATH = os.path.join(BASE_DIR, "data", "resumes", "MohamedHussein_DataAnalyst_Resume.pdf")
INSTRUCTOR_PATH = os.path.join(BASE_DIR, "data", "resumes", "MohamedHussein_ComputerScienceInstructor_Resume.pdf")


@pytest.fixture(autouse=True)
def clean_cache():
    clear_keyword_cache()
    yield
    clear_keyword_cache()


def test_resume_extraction_distinctiveness():
    # 1. Computer Vision Resume
    cv_text = extract_text_from_file(CV_PATH)
    cv_skills = extract_skills_from_resume_text(cv_text)
    
    assert "computer vision" in cv_skills or "opencv" in cv_skills
    assert "pytorch" in cv_skills
    # Must NOT extract teaching keywords from CV technical skills
    assert not any(k in cv_skills for k in ["teaching", "instructor", "teacher", "scratch", "mblock"])

    # 2. Data Scientist Resume
    ds_text = extract_text_from_file(DS_PATH)
    ds_skills = extract_skills_from_resume_text(ds_text)
    assert any(k in ds_skills for k in ["machine learning", "scikit-learn", "xgboost", "random forest"])
    assert not any(k in ds_skills for k in ["teaching", "instructor", "scratch", "mblock"])

    # 3. Data Analyst Resume
    da_text = extract_text_from_file(DA_PATH)
    da_skills = extract_skills_from_resume_text(da_text)
    assert any(k in da_skills for k in ["power bi", "dax", "excel", "dashboards", "kpi", "reporting"])
    assert not any(k in da_skills for k in ["opencv", "yolo", "teaching", "scratch"])

    # 4. Computer Science Instructor Resume
    inst_text = extract_text_from_file(INSTRUCTOR_PATH)
    inst_skills = extract_skills_from_resume_text(inst_text)
    assert any(k in inst_skills for k in ["teaching", "mentoring", "curriculum development", "scratch"])


def test_get_resume_keywords_for_role_config():
    cfg = {
        "ROLES": [
            {
                "title": "Computer Vision & AI",
                "resume_path": CV_PATH
            },
            {
                "title": "Data Analytics & BI",
                "resume_path": DA_PATH
            },
            {
                "title": "Teaching & STEM Instructor",
                "resume_path": INSTRUCTOR_PATH
            }
        ]
    }

    # Fetch for Computer Vision & AI
    cv_kws = get_resume_keywords_for_role("Computer Vision & AI", config=cfg)
    assert len(cv_kws) > 0
    assert "pytorch" in cv_kws
    assert not any(k in cv_kws for k in ["teaching", "scratch"])

    # Fetch for Teaching & STEM Instructor
    inst_kws = get_resume_keywords_for_role("Teaching & STEM Instructor", config=cfg)
    assert len(inst_kws) > 0
    assert any(k in inst_kws for k in ["teaching", "mentoring", "scratch"])


def test_cache_and_auto_refresh(tmp_path):
    test_pdf = tmp_path / "temp_resume.txt"
    test_pdf.write_text("TECHNICAL SKILLS\nLanguages: Python, SQL\nDeep Learning: PyTorch", encoding="utf-8")

    cfg = {
        "ROLES": [
            {"title": "Test Role", "resume_path": str(test_pdf)}
        ]
    }

    # First call extracts and caches
    kws_1 = get_resume_keywords_for_role("Test Role", config=cfg)
    assert "python" in kws_1
    assert "pytorch" in kws_1
    assert str(test_pdf) in _RESUME_SKILL_CACHE

    # Cache hit
    kws_cached = get_resume_keywords_for_role("Test Role", config=cfg)
    assert kws_cached == kws_1

    # Modify file mtime and contents
    time.sleep(0.05)
    test_pdf.write_text("TECHNICAL SKILLS\nLanguages: Python, C++\nVision: OpenCV, YOLO", encoding="utf-8")
    # Touch mtime to ensure it's newer
    new_mtime = time.time() + 2
    os.utime(str(test_pdf), (new_mtime, new_mtime))

    kws_refreshed = get_resume_keywords_for_role("Test Role", config=cfg)
    assert "opencv" in kws_refreshed or "yolo" in kws_refreshed
    assert "c++" in kws_refreshed


def test_unified_resume_keywords():
    cfg = {
        "ROLES": [
            {"title": "Computer Vision & AI", "resume_path": CV_PATH},
            {"title": "Data Analytics & BI", "resume_path": DA_PATH}
        ]
    }
    unified = get_unified_resume_keywords(config=cfg)
    assert len(unified) > 0
    assert "python" in unified
    assert "pytorch" in unified
    assert "power bi" in unified
