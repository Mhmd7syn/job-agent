import os
import sys
import json
import unittest
from unittest.mock import patch, MagicMock

# Ensure project root is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from core.whatsapp_bot import (
    clean_url, URL_REGEX, get_state, save_state, process_message,
    normalize_phone_number, get_candidate_phone, send_whatsapp_message,
    notify_whatsapp_candidate, sync_queued_whatsapp_jobs,
    record_new_whatsapp_job, get_and_clear_new_whatsapp_jobs,
    enqueue_incoming_message, process_incoming_payload,
    managed_ngrok_tunnel, managed_local_server, is_port_open,
    resolve_ngrok_bin, _process_whatsapp_queue
)


class TestWhatsAppBot(unittest.TestCase):

    def setUp(self):
        self.test_state_file = os.path.join(BASE_DIR, "output", "test_whatsapp_state.json")
        self.state_patcher = patch("core.whatsapp_bot.STATE_FILE", self.test_state_file)
        self.state_patcher.start()
        if os.path.exists(self.test_state_file):
            try:
                os.remove(self.test_state_file)
            except Exception:
                pass

        self.env_file = os.path.join(BASE_DIR, ".env")
        self.env_backup = None
        if os.path.exists(self.env_file):
            with open(self.env_file, "r", encoding="utf-8") as f:
                self.env_backup = f.read()

        import core.config as app_config
        self.orig_phone = getattr(app_config, "WHATSAPP_PHONE_NUMBER", None)
        self.orig_env_phone = os.environ.get("WHATSAPP_PHONE_NUMBER")

    def tearDown(self):
        self.state_patcher.stop()
        if os.path.exists(self.test_state_file):
            try:
                os.remove(self.test_state_file)
            except Exception:
                pass

        if self.env_backup is not None:
            with open(self.env_file, "w", encoding="utf-8") as f:
                f.write(self.env_backup)

        import core.config as app_config
        if self.orig_phone is not None:
            app_config.WHATSAPP_PHONE_NUMBER = self.orig_phone
        if self.orig_env_phone is not None:
            os.environ["WHATSAPP_PHONE_NUMBER"] = self.orig_env_phone
        else:
            os.environ.pop("WHATSAPP_PHONE_NUMBER", None)

    def test_clean_url(self):
        self.assertEqual(clean_url("https://linkedin.com/jobs/view/12345/"), "https://linkedin.com/jobs/view/12345/")
        self.assertEqual(clean_url("https://linkedin.com/jobs/view/12345."), "https://linkedin.com/jobs/view/12345")
        self.assertEqual(clean_url("https://linkedin.com/jobs/view/12345!"), "https://linkedin.com/jobs/view/12345")
        self.assertEqual(clean_url("www.wuzzuf.net/jobs/123"), "https://www.wuzzuf.net/jobs/123")

    def test_url_regex(self):
        text = "Check out this job at Google https://www.linkedin.com/jobs/view/99999 it looks great!"
        urls = URL_REGEX.findall(text)
        self.assertEqual(len(urls), 1)
        self.assertEqual(urls[0], "https://www.linkedin.com/jobs/view/99999")

    def test_normalize_phone_number(self):
        self.assertEqual(normalize_phone_number("01097344958"), "+201097344958")
        self.assertEqual(normalize_phone_number("+20 109 734 4958"), "+201097344958")
        self.assertEqual(normalize_phone_number("00201097344958"), "+201097344958")
        self.assertEqual(normalize_phone_number(""), "")

    def test_state_persistence(self):
        state = get_state()
        self.assertIn("queued_messages", state)

        save_state({"last_message_id": 45678, "queued_messages": []})
        loaded = get_state()
        self.assertEqual(loaded.get("last_message_id"), 45678)

    def test_record_and_clear_new_jobs(self):
        record_new_whatsapp_job("Backend Engineer")
        record_new_whatsapp_job("Data Scientist")
        jobs = get_and_clear_new_whatsapp_jobs()
        self.assertIn("Backend Engineer", jobs)
        self.assertIn("Data Scientist", jobs)
        self.assertEqual(get_and_clear_new_whatsapp_jobs(), [])

    @patch("core.whatsapp_bot.send_whatsapp_message")
    @patch("core.whatsapp_bot.scrape_job_from_url")
    @patch("core.whatsapp_bot.save_or_update_job")
    def test_process_message_with_url(self, mock_save, mock_scrape, mock_send):
        mock_scrape.return_value = {
            "job_id": "job123",
            "title": "Python Developer",
            "company": "Tech Inc",
            "location": "Cairo",
            "relevance_score": 85.0
        }
        mock_save.return_value = ({
            "job_id": "job123",
            "title": "Python Developer",
            "company": "Tech Inc",
            "location": "Cairo",
            "relevance_score": 85.0
        }, True)

        msg = {
            "from": "+201097344958",
            "text": "Hey check this job: https://www.linkedin.com/jobs/view/12345"
        }
        results = process_message(msg, candidate_phone="+201097344958", send_reply=True)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "added")
        self.assertEqual(results[0]["title"], "Python Developer")
        mock_send.assert_called()

    @patch("core.whatsapp_bot.send_whatsapp_message")
    @patch("core.whatsapp_bot.scrape_job_from_url")
    @patch("core.whatsapp_bot.save_or_update_job")
    def test_process_message_with_markdown_link(self, mock_save, mock_scrape, mock_send):
        mock_scrape.return_value = {
            "job_id": "job456",
            "title": "AI Researcher",
            "company": "Lab Co",
            "location": "Remote",
            "relevance_score": 90.0
        }
        mock_save.return_value = ({
            "job_id": "job456",
            "title": "AI Researcher",
            "company": "Lab Co",
            "location": "Remote",
            "relevance_score": 90.0
        }, True)

        msg = {
            "from": "+201097344958",
            "text": "Apply here: [Senior AI Researcher](https://wuzzuf.net/jobs/ai-123)"
        }
        results = process_message(msg, candidate_phone="+201097344958", send_reply=False)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "added")
        self.assertEqual(results[0]["title"], "AI Researcher")

    @patch("core.whatsapp_bot.send_whatsapp_message")
    @patch("core.whatsapp_bot.scrape_job_from_url")
    @patch("core.whatsapp_bot.save_or_update_job")
    def test_process_message_tags(self, mock_save, mock_scrape, mock_send):
        mock_scrape.return_value = {
            "job_id": "job789",
            "title": "DAAD Fellowship",
            "company": "DAAD",
            "location": "Germany",
            "relevance_score": 95.0,
            "job_type": "Scholarship"
        }
        mock_save.return_value = ({
            "job_id": "job789",
            "title": "DAAD Fellowship",
            "company": "DAAD",
            "relevance_score": 95.0,
            "job_type": "Scholarship",
            "status": "liked",
            "is_applied": 1
        }, True)

        msg = {
            "from": "+201097344958",
            "text": "#scholarship #liked #applied https://daad.de/scholarship/123"
        }
        results = process_message(msg, candidate_phone="+201097344958", send_reply=False)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["is_scholarship"])
        self.assertTrue(results[0]["is_liked"])
        self.assertTrue(results[0]["is_applied"])

    @patch("core.whatsapp_bot.get_candidate_phone", return_value="+201097344958")
    @patch("core.whatsapp_bot.send_whatsapp_message", return_value=True)
    def test_notify_whatsapp_candidate(self, mock_send, mock_phone):
        res = notify_whatsapp_candidate("⚠️ Auto-Pilot Failed: Timeout")
        self.assertTrue(res)
        mock_send.assert_called_once_with(phone="+201097344958", text="⚠️ Auto-Pilot Failed: Timeout")

    @patch("core.whatsapp_bot.process_message")
    @patch("core.whatsapp_bot.send_summary_reply")
    def test_sync_queued_whatsapp_jobs(self, mock_summary, mock_proc):
        mock_proc.return_value = [{
            "status": "added",
            "title": "Computer Vision Engineer",
            "company": "Vision AI",
            "job_data": {"job_id": "cv1"}
        }]
        enqueue_incoming_message(sender="+201097344958", text="https://linkedin.com/jobs/cv1", message_id="m1")

        res = sync_queued_whatsapp_jobs(candidate_phone="+201097344958", manage_tunnel=False)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["count"], 1)
        self.assertEqual(res["jobs"], ["Computer Vision Engineer"])

    def test_web_whatsapp_config_and_status_endpoints(self):
        from fastapi.testclient import TestClient
        from web.app import app

        client = TestClient(app)
        # Test status endpoint
        res = client.get("/api/whatsapp/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("is_configured", data)
        self.assertIn("phone_number", data)

        # Test config endpoint
        res_cfg = client.post("/api/whatsapp/config", json={"phone_number": "+201097344958"})
        self.assertEqual(res_cfg.status_code, 200)
        cfg_data = res_cfg.json()
        self.assertEqual(cfg_data["status"], "success")
        self.assertEqual(cfg_data["phone_number"], "+201097344958")

    def test_web_whatsapp_webhook_verification_and_receiver(self):
        from fastapi.testclient import TestClient
        from web.app import app

        client = TestClient(app)
        # 1. Valid Meta verification challenge
        res_ok = client.get("/api/whatsapp/webhook?hub.mode=subscribe&hub.challenge=987654&hub.verify_token=job_agent_verify_token")
        self.assertEqual(res_ok.status_code, 200)
        self.assertEqual(res_ok.text, "987654")

        # 2. Invalid verify token
        res_bad = client.get("/api/whatsapp/webhook?hub.mode=subscribe&hub.challenge=987654&hub.verify_token=wrong_token")
        self.assertEqual(res_bad.status_code, 403)

        # 3. Direct/legacy query parameter fallback
        res_direct = client.get("/api/whatsapp/webhook?hub_challenge=55512")
        self.assertEqual(res_direct.status_code, 200)
        self.assertEqual(res_direct.text, "55512")

        # 4. Meta incoming message POST payload
        meta_payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "201097344958",
                            "id": "wamid_123",
                            "type": "text",
                            "text": {"body": "https://linkedin.com/jobs/view/10001"}
                        }]
                    }
                }]
            }]
        }
        with patch("web.app.process_incoming_payload") as mock_proc:
            mock_proc.return_value = [{"status": "added", "title": "AI Engineer"}]
            post_res = client.post("/api/whatsapp/webhook", json=meta_payload)
            self.assertEqual(post_res.status_code, 200)
            self.assertEqual(post_res.json()["status"], "received")
            mock_proc.assert_called_once()

    @patch("core.whatsapp_bot.is_port_open")
    @patch("core.whatsapp_bot.resolve_ngrok_bin")
    @patch("subprocess.Popen")
    def test_managed_ngrok_tunnel_on_demand_spins_up_and_shuts_down(self, mock_popen, mock_resolve_bin, mock_port_open):
        mock_resolve_bin.return_value = r"C:\automation\ngrok\ngrok.exe"
        # Port 4040: initial check False (not external), loop check True (tunnel up)
        mock_port_open.side_effect = [False, True]

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        with managed_ngrok_tunnel(local_port=8000, domain="test-subdomain.ngrok-free.dev") as info:
            self.assertTrue(info["tunnel_active"])
            self.assertFalse(info["reused_external"])
            self.assertEqual(info["domain"], "test-subdomain.ngrok-free.dev")
            mock_popen.assert_called_once()
            args = mock_popen.call_args[0][0]
            self.assertIn("http", args)
            self.assertIn("8000", args)
            self.assertIn("--url=test-subdomain.ngrok-free.dev", args)
            # Should NOT be terminated while inside the context
            mock_proc.terminate.assert_not_called()

        # Immediately after exiting the context, ngrok must be terminated
        mock_proc.terminate.assert_called_once()
        mock_proc.wait.assert_called_once()

    @patch("core.whatsapp_bot.is_port_open")
    @patch("subprocess.Popen")
    def test_managed_ngrok_tunnel_preserves_external_tunnel(self, mock_popen, mock_port_open):
        # Port 4040 is ALREADY open before fetch started
        mock_port_open.return_value = True

        with managed_ngrok_tunnel(local_port=8000, domain="test-subdomain.ngrok-free.dev") as info:
            self.assertTrue(info["tunnel_active"])
            self.assertTrue(info["reused_external"])
            # MUST NOT spawn a new ngrok process
            mock_popen.assert_not_called()

        # MUST NOT terminate or kill anything when fetch completes
        mock_popen.assert_not_called()

    @patch("core.whatsapp_bot.is_port_open")
    @patch("core.whatsapp_bot.resolve_ngrok_bin")
    def test_managed_ngrok_tunnel_handles_missing_binary_or_domain(self, mock_resolve_bin, mock_port_open):
        mock_port_open.return_value = False
        mock_resolve_bin.return_value = None

        with managed_ngrok_tunnel(local_port=8000, domain="") as info:
            self.assertFalse(info["tunnel_active"])
            self.assertFalse(info["reused_external"])

    @patch("core.whatsapp_bot.is_port_open")
    @patch("subprocess.Popen")
    def test_managed_local_server_lifecycle(self, mock_popen, mock_port_open):
        # Case 1: Server already open on port 8000
        mock_port_open.return_value = True
        with managed_local_server(port=8000) as s_info:
            self.assertTrue(s_info["server_active"])
            self.assertTrue(s_info["reused_server"])
            mock_popen.assert_not_called()

        # Case 2: Server closed, starts temporary and shuts down
        mock_port_open.side_effect = [False, True]
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        with managed_local_server(port=8000) as s_info:
            self.assertTrue(s_info["server_active"])
            self.assertFalse(s_info["reused_server"])
            mock_popen.assert_called_once()
            mock_proc.terminate.assert_not_called()

        mock_proc.terminate.assert_called_once()
        mock_proc.wait.assert_called_once()

    @patch("core.whatsapp_bot.managed_local_server")
    @patch("core.whatsapp_bot.managed_ngrok_tunnel")
    @patch("core.whatsapp_bot._process_whatsapp_queue")
    def test_sync_queued_whatsapp_jobs_on_demand_lifecycle(self, mock_process_q, mock_tunnel, mock_server):
        mock_server.return_value.__enter__.return_value = {"server_active": True}
        mock_tunnel.return_value.__enter__.return_value = {"tunnel_active": True, "reused_external": False}
        mock_process_q.return_value = {"status": "success", "count": 2, "jobs": ["Job A", "Job B"]}

        res = sync_queued_whatsapp_jobs(candidate_phone="+201097344958", manage_tunnel=True, ingress_timeout=0)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["count"], 2)
        mock_server.assert_called_once()
        mock_tunnel.assert_called_once()
        mock_process_q.assert_called_once_with(candidate_phone="+201097344958")

    def test_desktop_app_has_no_persistent_ngrok_on_startup(self):
        desktop_app_path = os.path.join(BASE_DIR, "desktop_app.pyw")
        with open(desktop_app_path, "r", encoding="utf-8") as f:
            code = f.read()

        # Ensure no persistent ngrok process is started at startup
        self.assertNotIn("ngrok http", code)
        self.assertNotIn("ngrok_process = subprocess.Popen", code)
        self.assertNotIn("ngrok_process.terminate()", code)

    def test_job_agent_triggers_sync_at_cycle_start_only(self):
        job_agent_path = os.path.join(BASE_DIR, "job_agent.py")
        with open(job_agent_path, "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn('_sync_whatsapp_jobs(label_prefix="WhatsApp Pre-Run Sync")', code)
        self.assertNotIn('_sync_whatsapp_jobs(label_prefix="WhatsApp Post-Run Sync")', code)

    def test_web_static_app_js_no_idle_fetch_on_launch(self):
        app_js_path = os.path.join(BASE_DIR, "web", "static", "app.js")
        with open(app_js_path, "r", encoding="utf-8") as f:
            code = f.read()

        # Ensure no automatic setTimeout/setInterval triggers whatsapp sync on GUI load
        self.assertNotIn("syncWhatsAppJobsOnLaunch(false)", code)

    def test_web_refresh_endpoint_triggers_on_demand_sync(self):
        from fastapi.testclient import TestClient
        from web.app import app

        client = TestClient(app)
        with patch("web.app.sync_queued_whatsapp_jobs") as mock_sync:
            mock_sync.return_value = {"status": "success", "count": 1, "jobs": ["Lead Analyst"]}
            res = client.get("/api/whatsapp/sync")
            self.assertEqual(res.status_code, 200)
            mock_sync.assert_called_once_with(manage_tunnel=True)

    def test_process_incoming_payload_records_processed_ids_and_clears_queue(self):
        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "201097344958",
                            "id": "wamid_e2e_999",
                            "type": "text",
                            "text": {"body": "https://linkedin.com/jobs/view/999888"}
                        }]
                    }
                }]
            }]
        }
        with patch("core.whatsapp_bot.process_message") as mock_pm:
            mock_pm.return_value = [{"status": "added", "title": "Data Architect"}]
            results = process_incoming_payload(payload)
            self.assertEqual(len(results), 1)

            st = get_state()
            self.assertIn("wamid_e2e_999", st.get("processed_ids", []))
            # Should not leave unhandled item in queued_messages since it was already processed
            queued_ids = [m.get("id") for m in st.get("queued_messages", [])]
            self.assertNotIn("wamid_e2e_999", queued_ids)


if __name__ == "__main__":
    unittest.main()
