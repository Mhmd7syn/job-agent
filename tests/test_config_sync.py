import os
import json
import pytest
import core.config as app_config
from core.config import reload_config
from core.config_tuner import apply_config_updates


def test_reload_config_updates_globals(tmp_path, monkeypatch):
    test_config_file = tmp_path / "config.json"
    dummy_data = {
        "ROLES": [
            {"role_name": "Test Engineer", "terms": ["qa engineer", "automation tester"]}
        ],
        "LOCATION": ["Germany"],
        "SITES": ["linkedin", "indeed"],
        "RESUME_KEYWORDS": ["pytest", "selenium"],
        "TARGET_LEVELS": ["Senior / Lead"],
        "LEVEL_EXCLUDE": ["Intern / Student", "Fresh Graduate / Entry-level", "Junior", "Mid-Level", "Manager / Director"],
        "RESULTS_PER_TERM": 25,
        "HOURS_OLD": 48
    }
    test_config_file.write_text(json.dumps(dummy_data), encoding="utf-8")

    monkeypatch.setattr("core.config.config_json_path", str(test_config_file))
    
    result = reload_config()
    
    assert result["LOCATION"] == ["Germany"]
    assert app_config.LOCATION == ["Germany"]
    assert "qa engineer" in app_config.SEARCH_TERMS
    assert "automation tester" in app_config.SEARCH_TERMS
    assert app_config.SITES == ["linkedin", "indeed"]
    assert app_config.RESUME_KEYWORDS == ["pytest", "selenium"]
    assert app_config.TARGET_LEVELS == ["Senior / Lead"]
    assert "Junior" in app_config.LEVEL_EXCLUDE
    assert app_config.RESULTS_PER_TERM == 25
    assert app_config.HOURS_OLD == 48


def test_apply_config_updates_triggers_reload(tmp_path, monkeypatch):
    test_config_file = tmp_path / "config.json"
    initial_data = {
        "RESUME_KEYWORDS": ["python"],
        "EXCLUDE_KEYWORDS": []
    }
    test_config_file.write_text(json.dumps(initial_data), encoding="utf-8")

    monkeypatch.setattr("core.config.config_json_path", str(test_config_file))
    monkeypatch.setattr("core.config_tuner.CONFIG_PATH", str(test_config_file))
    
    reload_config()
    assert "python" in app_config.RESUME_KEYWORDS
    assert "docker" not in app_config.RESUME_KEYWORDS

    updates = [{"field": "RESUME_KEYWORDS", "type": "add", "value": "docker"}]
    apply_config_updates(updates)

    # In-memory global should now include docker
    assert "docker" in app_config.RESUME_KEYWORDS


def test_update_config_api_reloads_config(tmp_path, monkeypatch):
    test_config_file = tmp_path / "config.json"
    initial_data = {"LOCATION": ["Egypt"], "SITES": ["wuzzuf"]}
    test_config_file.write_text(json.dumps(initial_data), encoding="utf-8")

    monkeypatch.setattr("core.config.config_json_path", str(test_config_file))
    monkeypatch.setattr("web.app.CONFIG_JSON_PATH", str(test_config_file))
    reload_config()

    from fastapi.testclient import TestClient
    from web.app import app
    client = TestClient(app)

    new_payload = {"LOCATION": ["Remote"], "SITES": ["wuzzuf", "bayt"]}
    resp = client.post("/api/config", json=new_payload)
    assert resp.status_code == 200

    assert app_config.LOCATION == ["Remote"]
    assert app_config.SITES == ["wuzzuf", "bayt"]
