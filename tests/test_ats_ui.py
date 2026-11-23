import os
import sys
import time
import socket
import threading
import uvicorn
from unittest.mock import patch
import pytest
from playwright.sync_api import sync_playwright

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from web.app import app

TEST_PORT = 8011

def wait_for_server(port: int, timeout: float = 3.0) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return True
        except OSError:
            time.sleep(0.05)
    return False

def run_server():
    with patch("web.app.rescore_all_jobs", return_value=None):
        uvicorn.run(app, host="127.0.0.1", port=TEST_PORT, log_level="error")

@pytest.mark.ui
def test_ats_modal_ui():
    """Verify in headless browser that Company ATS & Web Form Co-Pilot modal opens and renders correctly."""
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    if not wait_for_server(TEST_PORT):
        pytest.fail(f"Uvicorn server failed to start on port {TEST_PORT}")

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
        page.route("**/*", lambda route: route.abort() if any(h in route.request.url for h in ["fonts.googleapis", "fonts.gstatic", "cdnjs.cloudflare"]) else route.continue_())

        console_errors = []
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)

        page.goto(f"http://127.0.0.1:{TEST_PORT}", wait_until="domcontentloaded")
        page.wait_for_selector(".job-card", timeout=5000)

        # 1. Check that #ats-copilot-modal exists in DOM
        modal = page.query_selector("#ats-copilot-modal")
        assert modal is not None, "#ats-copilot-modal should exist in DOM"

        # 2. Find a platform job in allJobs
        platform_job = page.evaluate("allJobs.find(j => (j.apply_type || '').toLowerCase() === 'platform')")
        assert platform_job is not None, "Should find at least one platform job in allJobs"

        # 3. Open the ATS Co-Pilot modal
        page.evaluate(f"openAtsCopilotModal('{platform_job['job_id']}')")
        page.wait_for_function("document.getElementById('ats-qc-name') && document.getElementById('ats-qc-name').textContent.trim().length > 0", timeout=3000)

        # 4. Verify ATS modal is visible
        modal_visible = page.is_visible("#ats-copilot-modal")
        assert modal_visible is True, "ATS Co-Pilot modal should be visible"

        # 5. Verify modal elements exist
        assert page.query_selector("#ats-job-title") is not None
        assert page.query_selector("#ats-job-company") is not None
        assert page.query_selector("#ats-platform-badge") is not None
        assert page.query_selector("#ats-cv-filename") is not None
        assert page.query_selector("#ats-portal-url-display") is not None
        assert page.query_selector("#ats-qc-name") is not None
        assert page.query_selector("#ats-qc-email") is not None
        assert page.query_selector("#ats-qc-phone") is not None
        assert page.query_selector("#ats-cover-letter-text") is not None
        assert page.query_selector("#ats-start-btn") is not None
        assert page.query_selector("#ats-applied-btn") is not None
        assert page.query_selector("#ats-logs-box") is not None

        # 6. Verify candidate data is populated
        name_text = page.inner_text("#ats-qc-name")
        assert len(name_text.strip()) > 0

        cv_text = page.inner_text("#ats-cv-filename")
        assert ("Resume.pdf" in cv_text or "CV.pdf" in cv_text or ".pdf" in cv_text.lower())

        cl_text = page.input_value("#ats-cover-letter-text")
        assert len(cl_text) > 50, "Cover letter textarea should be populated"

        # 7. Test hide modal
        page.evaluate("hideAtsCopilotModal()")
        time.sleep(0.1)
        assert page.is_visible("#ats-copilot-modal") is False, "ATS modal should be hidden after closing"

        browser.close()
        fatal_errors = [
            e for e in console_errors 
            if not any(k in e.lower() for k in ["favicon", "err_connection", "failed to load resource", "quic"])
        ]
        assert len(fatal_errors) == 0, f"Unexpected JS console errors: {fatal_errors}"

if __name__ == "__main__":
    test_ats_modal_ui()
    print("ATS UI Test Passed successfully!")
    sys.exit(0)
