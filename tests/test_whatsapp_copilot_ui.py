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
    uvicorn.run(app, host="127.0.0.1", port=8009, log_level="error")

def test_whatsapp_copilot_modal_ui():
    """Verify in headless browser that WhatsApp Co-Pilot modal opens and renders correctly."""
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

        page.goto("http://127.0.0.1:8009")
        page.wait_for_selector(".job-card", timeout=10000)

        # Check that #whatsapp-copilot-modal exists in DOM
        modal = page.query_selector("#whatsapp-copilot-modal")
        assert modal is not None, "#whatsapp-copilot-modal should exist in DOM"

        # Check Settings -> WhatsApp Mode and Lang fields exist
        wa_mode = page.query_selector("#apply-whatsapp-mode")
        assert wa_mode is not None, "#apply-whatsapp-mode should exist in settings"
        wa_lang = page.query_selector("#apply-whatsapp-lang")
        assert wa_lang is not None, "#apply-whatsapp-lang should exist in settings"

        # Find a WhatsApp job in allJobs
        wa_job = page.evaluate("allJobs.find(j => (j.apply_type || '').toLowerCase() === 'whatsapp')")
        assert wa_job is not None, "Should find at least one WhatsApp job in allJobs"

        # Open the WhatsApp Co-Pilot modal
        page.evaluate(f"openWhatsAppCopilotModal('{wa_job['job_id']}')")
        time.sleep(1.5)

        # Verify WhatsApp copilot modal is visible
        modal_visible = page.is_visible("#whatsapp-copilot-modal")
        assert modal_visible is True, "WhatsApp Co-Pilot modal should be visible"

        # Verify phone, target url, pitch textarea, cv info, and action buttons exist
        assert page.query_selector("#whatsapp-copilot-phone") is not None
        assert page.query_selector("#whatsapp-copilot-target-url") is not None
        assert page.query_selector("#whatsapp-copilot-pitch") is not None
        assert page.query_selector("#whatsapp-copilot-cv-filename") is not None
        assert page.query_selector("#whatsapp-copilot-desktop-btn") is not None
        assert page.query_selector("#whatsapp-copilot-applied-btn") is not None
        assert page.query_selector("#whatsapp-copilot-status-banner") is not None

        # Verify phone input is populated
        phone_val = page.input_value("#whatsapp-copilot-phone")
        assert len(phone_val) > 0, "Phone input should be populated"

        # Test hide modal
        page.evaluate("hideWhatsAppCopilotModal()")
        time.sleep(0.5)
        assert page.is_visible("#whatsapp-copilot-modal") is False, "WhatsApp Co-Pilot modal should be hidden after closing"

        browser.close()
        fatal_errors = [
            e for e in console_errors 
            if not any(k in e.lower() for k in ["favicon", "err_connection", "failed to load resource", "quic"])
        ]
        assert len(fatal_errors) == 0, f"Unexpected JS console errors: {fatal_errors}"

if __name__ == "__main__":
    test_whatsapp_copilot_modal_ui()
    print("WhatsApp UI Test Passed successfully!")
    sys.exit(0)
