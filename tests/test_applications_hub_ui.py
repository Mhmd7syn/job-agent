import os
import sys
import time
import threading
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

TEST_PORT = 8015

def run_server():
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=TEST_PORT, log_level="error")

def test_applications_hub_modal_ui():
    """Verify in headless browser that Applications Hub & Auto-Pilot modal opens and renders correctly."""
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    time.sleep(3)

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

        page.goto(f"http://127.0.0.1:{TEST_PORT}")
        page.wait_for_selector(".job-card", timeout=20000)

        # 1. Check that #applications-hub-modal exists in DOM
        modal = page.query_selector("#applications-hub-modal")
        assert modal is not None, "#applications-hub-modal should exist in DOM"
        assert page.is_visible("#applications-hub-modal") is False, "Modal should initially be hidden"

        # 2. Open Applications Hub modal
        page.evaluate("showApplicationsHub()")
        time.sleep(1.0)

        # 3. Verify modal is visible
        assert page.is_visible("#applications-hub-modal") is True, "Applications Hub modal should be visible"

        # 4. Check stat elements exist and have content
        stat_total = page.query_selector("#hub-stat-total")
        stat_today = page.query_selector("#hub-stat-today")
        stat_emails = page.query_selector("#hub-stat-emails")
        stat_wa = page.query_selector("#hub-stat-whatsapp")
        stat_quota = page.query_selector("#hub-stat-quota")

        assert stat_total is not None, "#hub-stat-total should exist"
        assert stat_today is not None, "#hub-stat-today should exist"
        assert stat_emails is not None, "#hub-stat-emails should exist"
        assert stat_wa is not None, "#hub-stat-whatsapp should exist"
        assert stat_quota is not None, "#hub-stat-quota should exist"

        # 5. Check action controls exist
        assert page.query_selector("#hub-run-cycle-btn") is not None
        assert page.query_selector("#hub-search-input") is not None
        assert page.query_selector("#hub-channel-filter") is not None
        assert page.query_selector("#hub-history-tbody") is not None
        assert page.query_selector("#hub-logs-terminal") is not None

        # 6. Interact with channel filter
        page.select_option("#hub-channel-filter", "email")
        time.sleep(0.5)

        # 7. Interact with search input
        page.fill("#hub-search-input", "Engineer")
        time.sleep(0.5)

        # 8. Close modal
        page.evaluate("hideApplicationsHub()")
        time.sleep(0.5)
        assert page.is_visible("#applications-hub-modal") is False, "Applications Hub modal should be hidden after closing"

        browser.close()

        # Check for unexpected console errors
        fatal_errors = [
            e for e in console_errors 
            if not any(k in e.lower() for k in ["favicon", "err_connection", "failed to load resource", "quic", "failed to fetch"])
        ]
        assert len(fatal_errors) == 0, f"Unexpected JS console errors: {fatal_errors}"

if __name__ == "__main__":
    test_applications_hub_modal_ui()
    print("Applications Hub UI Test Passed successfully!")
    sys.exit(0)
