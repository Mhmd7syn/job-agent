import os
import sys
import time
import socket
import threading
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from web.app import app
from core.database import get_jobs_by_apply_type, get_jobs_by_status


def wait_for_server(port: int, timeout: float = 3.0) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return True
        except OSError:
            time.sleep(0.05)
    return False


def test_database_get_jobs_by_apply_type():
    """Verify core.database.get_jobs_by_apply_type works correctly."""
    email_jobs = get_jobs_by_apply_type("email")
    assert isinstance(email_jobs, list)
    for j in email_jobs:
        assert j.get("apply_type") == "email" or j.get("apply_channel") == "email"

    wa_jobs = get_jobs_by_apply_type("whatsapp")
    assert isinstance(wa_jobs, list)
    for j in wa_jobs:
        assert j.get("apply_type") == "whatsapp" or j.get("apply_channel") == "whatsapp"


def test_api_jobs_apply_type_parameter():
    """Verify /api/jobs?apply_type=... endpoint returns filtered jobs."""
    client = TestClient(app)

    # All jobs
    res_all = client.get("/api/jobs")
    assert res_all.status_code == 200
    all_jobs = res_all.json()["jobs"]
    assert len(all_jobs) > 0

    # Filtered by email
    res_email = client.get("/api/jobs?apply_type=email")
    assert res_email.status_code == 200
    email_jobs = res_email.json()["jobs"]
    for j in email_jobs:
        assert (j.get("apply_type") or "").lower() == "email" or (j.get("apply_channel") or "").lower() == "email"

    # Filtered by whatsapp
    res_wa = client.get("/api/jobs?apply_type=whatsapp")
    assert res_wa.status_code == 200
    wa_jobs = res_wa.json()["jobs"]
    for j in wa_jobs:
        assert (j.get("apply_type") or "").lower() == "whatsapp" or (j.get("apply_channel") or "").lower() == "whatsapp"

    # Filtered by easy_apply
    res_ea = client.get("/api/jobs?apply_type=easy_apply")
    assert res_ea.status_code == 200
    ea_jobs = res_ea.json()["jobs"]
    for j in ea_jobs:
        assert (
            (j.get("apply_type") or "").lower() == "easy_apply"
            or (j.get("apply_channel") or "").lower() == "easy_apply"
            or j.get("is_easy_apply") in (1, True, "1", "true")
        )


TEST_UI_PORT = 8016


def run_ui_server():
    import uvicorn
    with patch("web.app.rescore_all_jobs", return_value=None):
        uvicorn.run(app, host="127.0.0.1", port=TEST_UI_PORT, log_level="error")


@pytest.mark.ui
def test_ui_apply_method_filter():
    """Verify in headless browser that the applying method filter dropdown works in the UI."""
    server_thread = threading.Thread(target=run_ui_server, daemon=True)
    server_thread.start()
    if not wait_for_server(TEST_UI_PORT):
        pytest.fail(f"Uvicorn server failed to start on port {TEST_UI_PORT}")

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception:
            try:
                browser = p.chromium.launch(channel="msedge", headless=True)
            except Exception:
                try:
                    browser = p.chromium.launch(channel="chrome", headless=True)
                except Exception as e:
                    pytest.skip(f"Playwright browser unavailable: {e}")

        page = browser.new_page()
        # Abort external CDN / font requests so tests never block on network stalls
        page.route("**/*", lambda route: route.abort() if any(h in route.request.url for h in ["fonts.googleapis", "fonts.gstatic", "cdnjs.cloudflare"]) else route.continue_())

        console_errors = []
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)

        page.goto(f"http://127.0.0.1:{TEST_UI_PORT}", wait_until="domcontentloaded")
        page.wait_for_selector(".job-card", timeout=5000)

        # 1. Verify #apply-method-filter dropdown exists
        dropdown = page.query_selector("#apply-method-filter")
        assert dropdown is not None, "#apply-method-filter dropdown must exist in DOM"

        # 2. Verify all expected options exist
        options = page.eval_on_selector_all("#apply-method-filter option", "opts => opts.map(o => o.value)")
        expected_values = ["all", "email", "whatsapp", "easy_apply", "form", "platform", "social_post", "job_board", "manual"]
        for exp in expected_values:
            assert exp in options, f"Option value '{exp}' must be present in #apply-method-filter"

        # 3. Check initial job count
        initial_count_text = page.inner_text("#job-count")
        initial_count = int(initial_count_text)
        assert initial_count > 0, "Dashboard should display jobs initially"

        # 4. Filter by Email
        page.select_option("#apply-method-filter", "email")
        page.wait_for_selector(".job-card .tag-channel-email", timeout=3000)
        email_count = int(page.inner_text("#job-count"))
        assert 0 < email_count <= initial_count, f"Email jobs count should be positive and <= initial (got {email_count})"

        rendered_badges = page.eval_on_selector_all(".job-card .tag-channel-email", "elements => elements.length")
        assert rendered_badges > 0, "Rendered cards should have tag-channel-email badge"

        # 5. Filter by WhatsApp
        page.select_option("#apply-method-filter", "whatsapp")
        page.wait_for_selector(".job-card .tag-channel-whatsapp", timeout=3000)
        wa_count = int(page.inner_text("#job-count"))
        assert 0 < wa_count <= initial_count, f"WhatsApp jobs count should be positive (got {wa_count})"
        wa_badges = page.eval_on_selector_all(".job-card .tag-channel-whatsapp", "elements => elements.length")
        assert wa_badges > 0, "Rendered cards should have tag-channel-whatsapp badge"

        # 6. Filter by Easy Apply
        page.select_option("#apply-method-filter", "easy_apply")
        page.wait_for_selector(".job-card .tag-channel-easyapply", timeout=3000)
        ea_count = int(page.inner_text("#job-count"))
        assert 0 < ea_count <= initial_count, f"Easy Apply jobs count should be positive (got {ea_count})"
        ea_badges = page.eval_on_selector_all(".job-card .tag-channel-easyapply", "elements => elements.length")
        assert ea_badges > 0, "Rendered cards should have tag-channel-easyapply badge"

        # 7. Switch back to All
        page.select_option("#apply-method-filter", "all")
        time.sleep(0.1)
        restored_count = int(page.inner_text("#job-count"))
        assert restored_count == initial_count, "Resetting filter to 'all' should restore original count"

        browser.close()

        fatal_errors = [
            e for e in console_errors
            if not any(k in e.lower() for k in ["favicon", "err_connection", "failed to load resource", "quic"])
        ]
        assert len(fatal_errors) == 0, f"Unexpected JS console errors: {fatal_errors}"


def test_multi_channel_classification_and_payload_serialization():
    """Verify multi-channel extraction priority and JSON payload serialization."""
    import json
    from core.apply_classifier import classify_and_extract

    job = {
        "title": "ML Engineer",
        "company": "MultiChannelCorp",
        "site": "linkedin",
        "job_url": "https://www.linkedin.com/jobs/view/777",
        "apply_url": "https://jobs.lever.co/multichannel/777",
        "description": "Send CV to talent@multichannel.ai or WhatsApp +201122334455",
    }
    res = classify_and_extract(job)
    assert res["apply_type"] == "platform"
    channels = res["apply_payload"]["available_channels"]
    assert [c["channel"] for c in channels] == ["platform", "email", "whatsapp", "job_board"]

    # Round-trip JSON serialization
    serialized = json.dumps(res["apply_payload"], ensure_ascii=False)
    deserialized = json.loads(serialized)
    assert len(deserialized["available_channels"]) == 4
    assert deserialized["available_channels"][1]["payload"]["recipient_email"] == "talent@multichannel.ai"
    assert deserialized["available_channels"][2]["payload"]["phone"] == "201122334455"


def test_api_job_detail_exposes_available_channels(tmp_path, monkeypatch):
    """Verify /api/jobs/{job_id} returns available_channels for multi-channel jobs."""
    import sqlite3
    import core.database as db_mod

    temp_db = tmp_path / "test_multichannel.db"
    monkeypatch.setattr(db_mod, "DB_PATH", str(temp_db))
    db_mod.init_db()
    db_mod.save_job({
        "job_id": "mc_job_1",
        "title": "AI Engineer",
        "company": "Acme",
        "location": "Cairo",
        "job_url": "https://www.linkedin.com/jobs/view/123",
        "apply_url": "https://boards.greenhouse.io/acme/jobs/123",
        "site": "linkedin",
        "description": "Email hr@acme.io or WhatsApp +201012345678",
    })

    client = TestClient(app)
    res = client.get("/api/jobs/mc_job_1")
    assert res.status_code == 200
    data = res.json()
    assert data["apply_type"] == "platform"
    assert [c["channel"] for c in data["available_channels"]] == ["platform", "email", "whatsapp", "job_board"]
    assert data["apply_payload"]["available_channels"] == data["available_channels"]
