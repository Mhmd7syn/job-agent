import os
import sys
import time
import threading
import uvicorn
from unittest.mock import patch
import pytest
from playwright.sync_api import sync_playwright

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Mock rescore_all_jobs so test server starts up instantly
patch("core.scorer.rescore_all_jobs", return_value=None).start()
patch("web.app.rescore_all_jobs", return_value=None).start()

from web.app import app

def run_server():
    uvicorn.run(app, host="127.0.0.1", port=8010, log_level="error")

def test_easy_apply_modal_ui():
    """Verify in headless browser that Easy Apply Co-Pilot modal opens and renders correctly."""
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    time.sleep(2)

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception:
            try:
                browser = p.chromium.launch(channel="chrome", headless=True)
            except Exception as e:
                pytest.skip(f"Playwright browser unavailable: {e}")
        page = browser.new_page()

        console_errors = []
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)

        page.goto("http://127.0.0.1:8010")
        page.wait_for_selector(".job-card", timeout=10000)

        # Check that #easy-apply-copilot-modal exists in DOM
        modal = page.query_selector("#easy-apply-copilot-modal")
        assert modal is not None, "#easy-apply-copilot-modal should exist in DOM"

        # Find an Easy Apply job in allJobs
        ea_job = page.evaluate("allJobs.find(j => (j.apply_type || '').toLowerCase() === 'easy_apply')")
        assert ea_job is not None, "Should find at least one Easy Apply job in allJobs"

        # Open the Easy Apply Co-Pilot modal
        page.evaluate(f"openEasyApplyCopilotModal('{ea_job['job_id']}')")
        time.sleep(1.5)

        # Verify Easy Apply modal is visible
        modal_visible = page.is_visible("#easy-apply-copilot-modal")
        assert modal_visible is True, "Easy Apply Co-Pilot modal should be visible"

        # Verify modal elements exist
        assert page.query_selector("#easy-apply-job-title") is not None
        assert page.query_selector("#easy-apply-job-company") is not None
        assert page.query_selector("#easy-apply-platform-badge") is not None
        assert page.query_selector("#easy-apply-contact-name") is not None
        assert page.query_selector("#easy-apply-cv-filename") is not None
        assert page.query_selector("#easy-apply-preview-sponsor") is not None
        assert page.query_selector("#easy-apply-start-btn") is not None
        assert page.query_selector("#easy-apply-applied-btn") is not None
        assert page.query_selector("#easy-apply-logs-box") is not None

        # Verify candidate name and CV filename are rendered
        name_text = page.inner_text("#easy-apply-contact-name")
        assert "Mohamed" in name_text

        cv_text = page.inner_text("#easy-apply-cv-filename")
        assert "Mohamed_Hussein_CV.pdf" in cv_text

        # Test hide modal
        page.evaluate("hideEasyApplyCopilotModal()")
        time.sleep(0.5)
        assert page.is_visible("#easy-apply-copilot-modal") is False, "Easy Apply modal should be hidden after closing"

        browser.close()
        fatal_errors = [
            e for e in console_errors 
            if not any(k in e.lower() for k in ["favicon", "err_connection", "failed to load resource", "quic"])
        ]
        assert len(fatal_errors) == 0, f"Unexpected JS console errors: {fatal_errors}"

if __name__ == "__main__":
    test_easy_apply_modal_ui()
    print("Easy Apply UI Test Passed successfully!")
    sys.exit(0)
