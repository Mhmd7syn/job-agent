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
from core.applicant_profile import load_profile, save_profile

TEST_PORT = 8017

def run_server():
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=TEST_PORT, log_level="error")

def test_autopilot_paused_settings_ui():
    """Verify in headless browser that Auto-Pilot is paused by default and can be resumed/paused from Settings."""
    # Ensure profile starts with enabled=False
    profile = load_profile()
    if "auto_apply_settings" not in profile:
        profile["auto_apply_settings"] = {}
    profile["auto_apply_settings"]["enabled"] = False
    save_profile(profile)

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

        page.goto(f"http://127.0.0.1:{TEST_PORT}")
        page.wait_for_selector(".job-card", timeout=10000)

        # 1. Test Applications Hub shows Paused badge & notice
        page.evaluate("showApplicationsHub()")
        time.sleep(1.0)
        assert page.is_visible("#applications-hub-modal") is True

        paused_badge = page.query_selector("#hub-paused-badge")
        assert paused_badge is not None, "#hub-paused-badge should exist in Hub modal"
        assert page.is_visible("#hub-paused-badge") is True, "Hub should display Paused in Settings badge"

        paused_notice = page.query_selector("#hub-paused-notice")
        assert paused_notice is not None, "#hub-paused-notice should exist in Hub modal"
        assert page.is_visible("#hub-paused-notice") is True, "Hub should display Paused notice banner"

        # 2. Click "Resume in Settings" inside Hub notice
        page.click("#hub-paused-notice button")
        time.sleep(1.0)

        # Applications Hub should be closed and Settings modal should be open
        assert page.is_visible("#applications-hub-modal") is False
        assert page.is_visible("#settings-modal") is True

        # Check that the Auto-Pilot status card exists and shows Paused
        status_card = page.query_selector("#autopilot-status-card")
        assert status_card is not None
        status_title = page.inner_text("#autopilot-status-title")
        assert "Paused" in status_title

        # Check toggle checkbox is unchecked
        cb_checked = page.is_checked("#apply-autopilot-enabled")
        assert cb_checked is False

        # 3. Click the toggle switch to Resume Auto-Pilot
        page.click(".toggle-switch")
        time.sleep(1.0)

        # UI should now reflect Active
        status_title_active = page.inner_text("#autopilot-status-title")
        assert "Active" in status_title_active

        # Check toggle checkbox is checked
        cb_checked_now = page.is_checked("#apply-autopilot-enabled")
        assert cb_checked_now is True

        # 4. Click Quick Action Button to Pause again
        page.click("#apply-autopilot-quick-btn")
        time.sleep(1.0)

        # UI should now reflect Paused again
        status_title_paused = page.inner_text("#autopilot-status-title")
        assert "Paused" in status_title_paused
        assert page.is_checked("#apply-autopilot-enabled") is False

        browser.close()

        # Check for unexpected console errors
        fatal_errors = [
            e for e in console_errors 
            if not any(k in e.lower() for k in ["favicon", "err_connection", "failed to load resource", "quic"])
        ]
        assert len(fatal_errors) == 0, f"Unexpected JS console errors: {fatal_errors}"

if __name__ == "__main__":
    test_autopilot_paused_settings_ui()
    print("Auto-Pilot Paused Settings UI Test Passed successfully!")
    sys.exit(0)
