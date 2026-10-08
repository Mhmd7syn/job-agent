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
    uvicorn.run(app, host="127.0.0.1", port=8008, log_level="error")

def test_email_copilot_modal_ui():
    """Verify in headless browser that Email Co-Pilot modal opens and renders correctly."""
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

        page.goto("http://127.0.0.1:8008")
        page.wait_for_selector(".job-card", timeout=10000)

        # Check that #email-copilot-modal exists in DOM
        modal = page.query_selector("#email-copilot-modal")
        assert modal is not None, "#email-copilot-modal should exist in DOM"

        # Check Settings -> Email Signature field exists
        sig_input = page.query_selector("#apply-email-signature")
        assert sig_input is not None, "#apply-email-signature should exist in settings"

        # Find an email job
        email_job = page.evaluate("allJobs.find(j => (j.apply_type || '').toLowerCase() === 'email')")
        assert email_job is not None, "Should find at least one email job in allJobs"

        # Open the Email Co-Pilot modal
        page.evaluate(f"openEmailCopilotModal('{email_job['job_id']}')")
        time.sleep(1.0)

        # Verify email copilot modal is visible
        modal_visible = page.is_visible("#email-copilot-modal")
        assert modal_visible is True, "Email Co-Pilot modal should be visible"

        # Verify recipient, subject, body, and cv card exist
        assert page.query_selector("#email-copilot-recipient") is not None
        assert page.query_selector("#email-copilot-subject") is not None
        assert page.query_selector("#email-copilot-body") is not None
        assert page.query_selector("#email-copilot-cv-filename") is not None
        assert page.query_selector("#email-copilot-outlook-btn") is not None
        assert page.query_selector("#email-copilot-gmail-btn") is None, "Gmail button should be removed as requested"
        assert page.query_selector("#email-copilot-applied-btn") is not None
        assert page.query_selector("#email-copilot-status-banner") is not None

        # Test hide modal
        page.evaluate("hideEmailCopilotModal()")
        time.sleep(0.5)
        assert page.is_visible("#email-copilot-modal") is False, "Email Co-Pilot modal should be hidden after closing"

        browser.close()
        fatal_errors = [
            e for e in console_errors 
            if not any(k in e.lower() for k in ["favicon", "err_connection", "failed to load resource", "quic", "failed to fetch"])
        ]
        assert len(fatal_errors) == 0, f"Unexpected JS console errors: {fatal_errors}"

if __name__ == "__main__":
    test_email_copilot_modal_ui()
    print("UI Test Passed successfully!")
    sys.exit(0)
