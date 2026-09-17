import pytest
import json
from core.career_levels import (
    CAREER_LEVEL_CATEGORIES,
    CAREER_LEVEL_SYNONYMS,
    expand_levels,
    get_excluded_levels,
    normalize_category_name
)
from core.scorer import calculate_score
import core.config as app_config
from core.config import reload_config


def test_career_level_categories_complete():
    expected = [
        "Intern / Student",
        "Fresh Graduate / Entry-level",
        "Junior",
        "Mid-Level",
        "Senior / Lead",
        "Manager / Director"
    ]
    assert CAREER_LEVEL_CATEGORIES == expected
    for cat in expected:
        assert cat in CAREER_LEVEL_SYNONYMS
        assert len(CAREER_LEVEL_SYNONYMS[cat]) > 0


def test_expand_levels_canonical():
    expanded = expand_levels(["Junior", "Senior / Lead"])
    # Junior synonyms
    assert "junior" in expanded
    assert "jr" in expanded
    assert "associate" in expanded
    # Senior synonyms
    assert "senior" in expanded
    assert "sr" in expanded
    assert "lead" in expanded
    assert "principal" in expanded


def test_expand_levels_legacy_and_custom():
    # Legacy raw keyword "intern" should expand to intern category synonyms
    expanded = expand_levels(["intern"])
    assert "intern" in expanded
    assert "internship" in expanded
    assert "student" in expanded

    # Custom keyword should be preserved
    expanded_custom = expand_levels(["fellowship_researcher"])
    assert "fellowship_researcher" in expanded_custom


def test_get_excluded_levels_auto_detection():
    # Target only Junior and Intern
    targets = ["Junior", "Intern / Student"]
    excluded = get_excluded_levels(targets)
    assert "Fresh Graduate / Entry-level" in excluded
    assert "Mid-Level" in excluded
    assert "Senior / Lead" in excluded
    assert "Manager / Director" in excluded
    assert "Junior" not in excluded
    assert "Intern / Student" not in excluded

    # Explicit exclusions override
    explicit = ["Manager / Director"]
    assert get_excluded_levels(targets, explicit_level_exclude=explicit) == explicit


def test_scorer_disqualifies_excluded_seniority():
    cfg = {
        "ROLES": [{"title": "Python Dev", "terms": ["python"]}],
        "RESUME_KEYWORDS": ["python", "django", "docker"],
        "EXCLUDE_KEYWORDS": [],
        "TARGET_LOCATIONS": ["cairo"],
        "TARGET_LEVELS": ["Junior", "Intern / Student"],
        "LEVEL_EXCLUDE": ["Senior / Lead", "Manager / Director", "Mid-Level"],
        "EXCLUDED_COMPANIES": [],
        "FAVORITE_COMPANIES": []
    }

    # Senior job should be hard-disqualified (score = 0)
    senior_job = {
        "title": "Senior Python Developer",
        "company": "Tech Corp",
        "location": "Cairo",
        "description": "Python, Django, Docker required.",
        "job_type": "Full Time",
        "career_level": "Senior"
    }
    assert calculate_score(senior_job, config=cfg) == 0

    # Lead job should be hard-disqualified
    lead_job = {
        "title": "Lead Python Engineer",
        "company": "Tech Corp",
        "location": "Cairo",
        "description": "Python, Django, Docker required.",
        "job_type": "Full Time",
        "career_level": ""
    }
    assert calculate_score(lead_job, config=cfg) == 0

    # Director / Manager job should be hard-disqualified
    mgr_job = {
        "title": "Engineering Manager",
        "company": "Tech Corp",
        "location": "Cairo",
        "description": "Python required.",
        "job_type": "Full Time",
        "career_level": "Manager"
    }
    assert calculate_score(mgr_job, config=cfg) == 0

    # Mid-level job should be hard-disqualified
    mid_job = {
        "title": "Mid-Level Python Developer",
        "company": "Tech Corp",
        "location": "Cairo",
        "description": "Python required.",
        "job_type": "Full Time",
        "career_level": "Mid-Level"
    }
    assert calculate_score(mid_job, config=cfg) == 0


def test_scorer_boosts_target_seniority():
    cfg = {
        "ROLES": [{"title": "Python Dev", "terms": ["python"]}],
        "RESUME_KEYWORDS": ["python", "django", "docker"],
        "EXCLUDE_KEYWORDS": [],
        "TARGET_LOCATIONS": ["cairo"],
        "TARGET_LEVELS": ["Junior", "Intern / Student"],
        "LEVEL_EXCLUDE": ["Senior / Lead", "Manager / Director", "Mid-Level"],
        "EXCLUDED_COMPANIES": [],
        "FAVORITE_COMPANIES": []
    }

    # Junior job receives +15 boost
    jr_job = {
        "title": "Junior Python Developer",
        "company": "Tech Corp",
        "location": "Cairo",
        "description": "Python, Django, Docker required.",
        "job_type": "Full Time",
        "career_level": "Junior"
    }
    jr_score = calculate_score(jr_job, config=cfg)
    assert jr_score > 0

    # Plain job without seniority tag
    plain_job = {
        "title": "Python Developer",
        "company": "Tech Corp",
        "location": "Cairo",
        "description": "Python, Django, Docker required.",
        "job_type": "Full Time",
        "career_level": ""
    }
    plain_score = calculate_score(plain_job, config=cfg)
    assert plain_score > 0

    # Junior job score should be exactly plain_score + 15
    assert jr_score == plain_score + 15


def test_scorer_non_manager_negation_guard():
    cfg = {
        "ROLES": [{"title": "Python Dev", "terms": ["python"]}],
        "RESUME_KEYWORDS": ["python", "django", "docker"],
        "EXCLUDE_KEYWORDS": [],
        "TARGET_LOCATIONS": ["cairo"],
        "TARGET_LEVELS": ["Junior", "Mid-Level"],
        "LEVEL_EXCLUDE": ["Manager / Director", "Senior / Lead"],
        "EXCLUDED_COMPANIES": [],
        "FAVORITE_COMPANIES": []
    }

    # Wuzzuf job stating "Experienced (Non-Manager)" should NOT be rejected as a Manager
    wuzzuf_job = {
        "title": "Python Developer",
        "company": "Tech Corp",
        "location": "Cairo",
        "description": "Python, Django, Docker required.",
        "job_type": "Full Time",
        "career_level": "Experienced (Non-Manager)"
    }
    score = calculate_score(wuzzuf_job, config=cfg)
    assert score > 0


def test_config_sync_level_exclude(tmp_path, monkeypatch):
    test_config_file = tmp_path / "config.json"
    dummy_data = {
        "LOCATION": ["Egypt"],
        "TARGET_LEVELS": ["Junior", "Intern / Student"],
        "LEVEL_EXCLUDE": ["Senior / Lead", "Manager / Director", "Mid-Level"]
    }
    test_config_file.write_text(json.dumps(dummy_data), encoding="utf-8")

    monkeypatch.setattr("core.config.config_json_path", str(test_config_file))
    monkeypatch.setattr("web.app.CONFIG_JSON_PATH", str(test_config_file))

    reload_config()
    assert app_config.TARGET_LEVELS == ["Junior", "Intern / Student"]
    assert app_config.LEVEL_EXCLUDE == ["Senior / Lead", "Manager / Director", "Mid-Level"]

    from fastapi.testclient import TestClient
    from web.app import app
    client = TestClient(app)

    new_payload = {
        "LOCATION": ["Egypt"],
        "TARGET_LEVELS": ["Senior / Lead"],
        "LEVEL_EXCLUDE": ["Junior", "Intern / Student", "Fresh Graduate / Entry-level"]
    }
    resp = client.post("/api/config", json=new_payload)
    assert resp.status_code == 200

    assert app_config.TARGET_LEVELS == ["Senior / Lead"]
    assert app_config.LEVEL_EXCLUDE == ["Junior", "Intern / Student", "Fresh Graduate / Entry-level"]


def test_cv_parser_heuristic_canonical_levels():
    from core.cv_parser import parse_cv_heuristic
    cv_text = """
    John Doe
    Python Developer
    Skills: Python, SQL, Machine Learning, PyTorch, Scikit-learn
    Experience: 1 year as Junior Software Engineer
    Education: B.Sc. Computer Science
    """
    res = parse_cv_heuristic(cv_text)
    assert res["status"] == "success"
    # Target levels must strictly be from CAREER_LEVEL_CATEGORIES
    for lvl in res["target_levels"]:
        assert lvl in CAREER_LEVEL_CATEGORIES
    for lvl in res["levels_to_remove"]:
        assert lvl in CAREER_LEVEL_CATEGORIES


def test_config_tuner_proposals_and_sync():
    from core.config_tuner import generate_proposals, apply_single_proposal
    cfg = {
        "TARGET_LEVELS": ["Junior"],
        "LEVEL_EXCLUDE": ["Intern / Student", "Fresh Graduate / Entry-level", "Mid-Level", "Senior / Lead", "Manager / Director"]
    }
    # Propose adding legacy string "intern"
    updates = {"target_levels_add": ["intern"]}
    proposals = generate_proposals(updates, current_config=cfg)
    assert len(proposals) == 1
    # Should be normalized to canonical category
    assert proposals[0]["value"] == "Intern / Student"

    # Apply proposal and ensure LEVEL_EXCLUDE auto-syncs
    modified = apply_single_proposal(proposals[0], cfg)
    assert modified is True
    assert "Intern / Student" in cfg["TARGET_LEVELS"]
    assert "Intern / Student" not in cfg["LEVEL_EXCLUDE"]
    assert "Senior / Lead" in cfg["LEVEL_EXCLUDE"]

