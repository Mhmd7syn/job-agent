import os
import time
import pytest
from unittest.mock import patch, MagicMock
import core.role_keywords as role_keywords
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
)
from core.cv_parser import extract_text_from_file

CV_PATH = ""
DS_PATH = ""
DA_PATH = ""
INSTRUCTOR_PATH = ""


@pytest.fixture(autouse=True)
def isolated_test_environment(tmp_path, monkeypatch):
    """Isolate disk cache, Gemini client, and synthetic resume fixtures per test."""
    global CV_PATH, DS_PATH, DA_PATH, INSTRUCTOR_PATH

    cache_file = tmp_path / "resume_keywords_cache.json"
    monkeypatch.setattr(role_keywords, "CACHE_FILE", str(cache_file))

    def _fail_unmocked_gemini(*args, **kwargs):
        raise AssertionError("Unmocked call to core.role_keywords.generate_content_resilient")

    # Default to offline mode unless a test explicitly patches Gemini mocks
    monkeypatch.setattr(role_keywords, "get_gemini_client", lambda *args, **kwargs: None)
    monkeypatch.setattr(role_keywords, "generate_content_resilient", _fail_unmocked_gemini)

    resumes_dir = tmp_path / "resumes"
    resumes_dir.mkdir()

    cv_file = resumes_dir / "cv_engineer.txt"
    cv_file.write_text(
        "TECHNICAL SKILLS\n"
        "Languages: Python, C++\n"
        "Computer Vision & AI: Computer Vision, OpenCV, PyTorch, YOLO, Object Detection\n",
        encoding="utf-8",
    )

    ds_file = resumes_dir / "data_scientist.txt"
    ds_file.write_text(
        "TECHNICAL SKILLS\n"
        "Languages: Python, SQL\n"
        "ML: Machine Learning, Scikit-learn, XGBoost, Random Forest, Pandas\n",
        encoding="utf-8",
    )

    da_file = resumes_dir / "data_analyst.txt"
    da_file.write_text(
        "TECHNICAL SKILLS\n"
        "BI & Analytics: Power BI, DAX, Excel, SQL, Dashboards, KPI, Reporting\n",
        encoding="utf-8",
    )

    inst_file = resumes_dir / "cs_instructor.txt"
    inst_file.write_text(
        "TECHNICAL SKILLS\n"
        "Instruction: Teaching, Mentoring, Curriculum Development, Scratch, Python, Robotics\n",
        encoding="utf-8",
    )

    CV_PATH = str(cv_file)
    DS_PATH = str(ds_file)
    DA_PATH = str(da_file)
    INSTRUCTOR_PATH = str(inst_file)

    clear_keyword_cache()
    yield
    clear_keyword_cache()


def _mock_gemini_keywords_by_resume(raw_text: str):
    """Deterministic mock keyword extraction payload tailored to resume content."""
    lower = raw_text.lower()
    if "scratch" in lower or "teaching" in lower:
        return ["teaching", "mentoring", "curriculum development", "scratch", "python"]
    if "power bi" in lower or "dax" in lower:
        return ["power bi", "dax", "excel", "sql", "dashboards"]
    if "xgboost" in lower or "scikit-learn" in lower:
        return ["python", "sql", "machine learning", "scikit-learn", "xgboost"]
    return ["computer vision", "opencv", "pytorch", "yolo", "python"]


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

    with patch("core.role_keywords.extract_keywords_with_gemini", side_effect=_mock_gemini_keywords_by_resume) as mock_gemini:
        # Fetch for Computer Vision & AI
        cv_kws = get_resume_keywords_for_role("Computer Vision & AI", config=cfg)
        assert len(cv_kws) > 0
        assert "pytorch" in cv_kws
        assert not any(k in cv_kws for k in ["teaching", "scratch"])

        # Fetch for Teaching & STEM Instructor
        inst_kws = get_resume_keywords_for_role("Teaching & STEM Instructor", config=cfg)
        assert len(inst_kws) > 0
        assert any(k in inst_kws for k in ["teaching", "mentoring", "scratch"])

        assert mock_gemini.call_count == 2


def test_cache_and_auto_refresh(tmp_path):
    test_pdf = tmp_path / "temp_resume.txt"
    test_pdf.write_text("TECHNICAL SKILLS\nLanguages: Python, SQL\nDeep Learning: PyTorch", encoding="utf-8")

    cfg = {
        "ROLES": [
            {"title": "Test Role", "resume_path": str(test_pdf)}
        ]
    }

    with patch("core.role_keywords.get_gemini_client", return_value=None):
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
    with patch("core.role_keywords.extract_keywords_with_gemini", side_effect=_mock_gemini_keywords_by_resume) as mock_gemini:
        unified = get_unified_resume_keywords(config=cfg)
        assert len(unified) > 0
        assert "python" in unified
        assert "pytorch" in unified
        assert "power bi" in unified
        assert mock_gemini.call_count == 2


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
            assert os.path.exists(role_keywords.CACHE_FILE)

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

    with patch("core.role_keywords.extract_keywords_with_gemini", side_effect=_mock_gemini_keywords_by_resume) as mock_gemini:
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

        assert mock_gemini.call_count == 1


def test_extract_keywords_from_resume_path():
    """Verify standalone extract_keywords_from_resume_path extracts and caches properly."""
    with patch("core.role_keywords.extract_keywords_with_gemini", side_effect=_mock_gemini_keywords_by_resume) as mock_gemini:
        # 1. Valid file extraction
        kws = extract_keywords_from_resume_path(CV_PATH, force_refresh=True)
        assert len(kws) > 0
        assert "pytorch" in kws
        assert mock_gemini.call_count == 1

        # 2. Non-existent file returns []
        assert extract_keywords_from_resume_path("non_existent_resume_123.pdf") == []

        # 3. Empty string returns []
        assert extract_keywords_from_resume_path("") == []
        assert mock_gemini.call_count == 1
