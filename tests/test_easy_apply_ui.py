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

TEST_PORT = 8010

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
def test_easy_apply_modal_ui():
    """Verify in headless browser that Easy Apply Co-Pilot modal opens and renders correctly."""
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

        # Check that #easy-apply-copilot-modal exists in DOM
        modal = page.query_selector("#easy-apply-copilot-modal")
        assert modal is not None, "#easy-apply-copilot-modal should exist in DOM"

        # Find an Easy Apply job in allJobs
        ea_job = page.evaluate("allJobs.find(j => (j.apply_type || '').toLowerCase() === 'easy_apply')")
        assert ea_job is not None, "Should find at least one Easy Apply job in allJobs"

        # Open the Easy Apply Co-Pilot modal
        page.evaluate(f"openEasyApplyCopilotModal('{ea_job['job_id']}')")
        page.wait_for_function("document.getElementById('easy-apply-contact-name') && document.getElementById('easy-apply-contact-name').textContent.trim().length > 0", timeout=3000)

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
        assert len(name_text.strip()) > 0

        cv_text = page.inner_text("#easy-apply-cv-filename")
        assert ("Resume.pdf" in cv_text or "CV.pdf" in cv_text or ".pdf" in cv_text.lower())

        # Test hide modal
        page.evaluate("hideEasyApplyCopilotModal()")
        time.sleep(0.1)
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
