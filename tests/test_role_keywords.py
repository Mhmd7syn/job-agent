import os
import time
import pytest
from unittest.mock import patch, MagicMock
from core.role_keywords import (
    extract_skills_from_resume_text,
    extract_keywords_with_gemini,
    normalize_and_deduplicate_keywords,
    get_resume_keywords_for_role,
    get_all_role_keywords,
    get_unified_resume_keywords,
    extract_keywords_from_resume_path,
    clear_keyword_cache,
    _RESUME_SKILL_CACHE,
    CACHE_FILE
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


def test_extract_keywords_with_gemini_success():
    mock_resp = MagicMock()
    mock_resp.text = '{"keywords": ["python", "pytorch", "gcp", "docker", "microservices", "ci/cd", "rag"]}'

    with patch("core.role_keywords.get_gemini_client", return_value=MagicMock()):
        with patch("core.role_keywords.generate_content_resilient", return_value=(mock_resp, "gemini-flash-lite-latest")):
            kws = extract_keywords_with_gemini("Experienced AI engineer with Docker, GCP and microservices.")
            assert "python" in kws
            assert "pytorch" in kws
            assert "google cloud" in kws  # Normalized via skill_ontology from 'gcp'
            assert "docker" in kws
            assert "microservice" in kws
            assert "ci/cd" in kws
            assert "rag" in kws


def test_normalize_and_deduplicate_keywords():
    from core.skill_ontology import ontology
    raw = ["PYTHON", "python", "GCP", "google cloud", "k8s", "Docker", ""]
    norm = normalize_and_deduplicate_keywords(raw)
    assert norm == ["python", "google cloud", ontology.get_canonical_skill("k8s"), "docker"]


def test_disk_cache_persistence_and_mtime_invalidation(tmp_path):
    test_pdf = tmp_path / "cv_persist_test.txt"
    test_pdf.write_text("Experience: Python backend with FastAPI and Docker.", encoding="utf-8")

    cfg = {"ROLES": [{"title": "Cloud Backend", "resume_path": str(test_pdf)}]}

    mock_resp = MagicMock()
    mock_resp.text = '{"keywords": ["python", "fastapi", "docker"]}'

    with patch("core.role_keywords.get_gemini_client", return_value=MagicMock()):
        with patch("core.role_keywords.generate_content_resilient", return_value=(mock_resp, "gemini-flash-lite-latest")) as mock_call:
            # 1. First call triggers LLM extraction and writes cache to disk and memory
            kws_1 = get_resume_keywords_for_role("Cloud Backend", config=cfg)
            assert mock_call.call_count == 1
            assert "fastapi" in kws_1
            assert os.path.exists(CACHE_FILE)

            # 2. Second call with unchanged mtime: hits cache, zero LLM calls
            kws_2 = get_resume_keywords_for_role("Cloud Backend", config=cfg)
            assert mock_call.call_count == 1
            assert kws_2 == kws_1

            # 3. Touch mtime: invalidates cache and triggers new LLM extraction
            time.sleep(0.05)
            mock_resp.text = '{"keywords": ["python", "fastapi", "docker", "kubernetes"]}'
            new_mtime = time.time() + 5
            os.utime(str(test_pdf), (new_mtime, new_mtime))

            kws_3 = get_resume_keywords_for_role("Cloud Backend", config=cfg)
            assert mock_call.call_count == 2
            assert "kubernete" in kws_3


def test_extract_keywords_gemini_offline_fallback(tmp_path):
    test_pdf = tmp_path / "cv_fallback.txt"
    test_pdf.write_text("TECHNICAL SKILLS\nLanguages: Python, SQL\nLibraries: PyTorch", encoding="utf-8")

    cfg = {"ROLES": [{"title": "AI Role", "resume_path": str(test_pdf)}]}

    # Simulate Gemini failing
    with patch("core.role_keywords.get_gemini_client", return_value=None):
        kws = get_resume_keywords_for_role("AI Role", config=cfg)
        # Should gracefully fall back to regex matcher
        assert "python" in kws
        assert "pytorch" in kws


def test_explicit_role_resume_keywords_priority():
    """Verify that user-edited role['resume_keywords'] takes precedence over CV extraction."""
    cfg = {
        "ROLES": [
            {
                "title": "Computer Vision & AI",
                "resume_path": CV_PATH,
                "resume_keywords": ["custom_skill_a", "fastapi", "docker"]
            },
            {
                "title": "Data Analytics & BI",
                "resume_path": DA_PATH
                # No resume_keywords, should fall back to CV extraction
            },
            {
                "title": "Empty Explicit Keywords Role",
                "resume_path": CV_PATH,
                "resume_keywords": []
            }
        ]
    }

    # 1. Explicit resume_keywords priority
    cv_kws = get_resume_keywords_for_role("Computer Vision & AI", config=cfg)
    assert cv_kws == ["custom_skill_a", "fastapi", "docker"]
    # CV file would normally yield 'pytorch', 'opencv', etc., which must NOT be present
    assert "pytorch" not in cv_kws

    # 2. Fall back to CV extraction when resume_keywords is absent
    da_kws = get_resume_keywords_for_role("Data Analytics & BI", config=cfg)
    assert any(k in da_kws for k in ["power bi", "dax", "excel", "dashboards"])

    # 3. Explicit empty resume_keywords returns empty list
    empty_kws = get_resume_keywords_for_role("Empty Explicit Keywords Role", config=cfg)
    assert empty_kws == []


def test_extract_keywords_from_resume_path():
    """Verify standalone extract_keywords_from_resume_path extracts and caches properly."""
    # 1. Valid file extraction
    kws = extract_keywords_from_resume_path(CV_PATH, force_refresh=True)
    assert len(kws) > 0
    assert "pytorch" in kws

    # 2. Non-existent file returns []
    assert extract_keywords_from_resume_path("non_existent_resume_123.pdf") == []

    # 3. Empty string returns []
    assert extract_keywords_from_resume_path("") == []


