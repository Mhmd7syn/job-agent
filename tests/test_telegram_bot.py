import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Ensure project root is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from core.telegram_bot import (
    clean_url, URL_REGEX, get_state, save_state, process_message
)


class TestTelegramBot(unittest.TestCase):

    def setUp(self):
        self.test_state_file = os.path.join(BASE_DIR, "output", "test_telegram_state.json")
        self.state_patcher = patch("core.telegram_bot.STATE_FILE", self.test_state_file)
        self.state_patcher.start()
        if os.path.exists(self.test_state_file):
            try:
                os.remove(self.test_state_file)
            except Exception:
                pass

    def tearDown(self):
        self.state_patcher.stop()
        if os.path.exists(self.test_state_file):
            try:
                os.remove(self.test_state_file)
            except Exception:
                pass

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

    def test_state_persistence(self):
        test_state_file = os.path.join(BASE_DIR, "output", "test_telegram_state.json")
        with patch("core.telegram_bot.STATE_FILE", test_state_file):
            if os.path.exists(test_state_file):
                os.remove(test_state_file)

            # Initially 0
            state = get_state()
            self.assertEqual(state.get("last_update_id"), 0)

            # Save state
            save_state({"last_update_id": 45678})
            updated = get_state()
            self.assertEqual(updated.get("last_update_id"), 45678)

            if os.path.exists(test_state_file):
                os.remove(test_state_file)

    @patch("core.telegram_bot.send_message")
    @patch("core.telegram_bot.send_chat_action")
    @patch("core.telegram_bot.scrape_job_from_url")
    @patch("core.telegram_bot.save_or_update_job")
    def test_process_message_with_url(self, mock_save, mock_scrape, mock_action, mock_send):
        mock_scrape.return_value = {
            "job_id": "test_1",
            "title": "Senior Python Developer",
            "company": "Vodafone",
            "location": "Cairo",
            "relevance_score": 88.5
        }
        mock_save.return_value = ({
            "job_id": "test_1",
            "title": "Senior Python Developer",
            "company": "Vodafone",
            "location": "Cairo",
            "relevance_score": 88.5
        }, True)

        msg = {
            "chat": {"id": 12345678},
            "from": {"id": 12345678, "username": "testuser"},
            "text": "Hey check this role: https://linkedin.com/jobs/view/123456"
        }

        process_message("fake_token", msg, allowed_chat_id="12345678")

        mock_scrape.assert_called_once_with(url="https://linkedin.com/jobs/view/123456", scraper_type="auto", is_scholarship=False)
        mock_save.assert_called_once()
        mock_send.assert_called_once()
        reply_text = mock_send.call_args[0][2]
        self.assertIn("Senior Python Developer", reply_text)
        self.assertIn("Vodafone", reply_text)
        self.assertIn("88.5%", reply_text)

    @patch("core.telegram_bot.send_message")
    @patch("core.telegram_bot.send_chat_action")
    @patch("core.telegram_bot.scrape_job_from_url")
    @patch("core.telegram_bot.save_or_update_job")
    def test_process_message_with_raw_text(self, mock_save, mock_scrape, mock_action, mock_send):
        mock_scrape.return_value = {
            "job_id": "test_2",
            "title": "Data Analyst",
            "company": "Etisalat",
            "location": "Giza",
            "relevance_score": 75.0
        }
        mock_save.return_value = ({
            "job_id": "test_2",
            "title": "Data Analyst",
            "company": "Etisalat",
            "location": "Giza",
            "relevance_score": 75.0
        }, True)

        msg = {
            "chat": {"id": 12345678},
            "from": {"id": 12345678, "username": "testuser"},
            "text": "We are hiring a Data Analyst at Etisalat located in Giza with Python and SQL experience."
        }

        process_message("fake_token", msg, allowed_chat_id="12345678")

        mock_scrape.assert_called_once_with(url="", raw_text=msg["text"], scraper_type="generic", is_scholarship=False)
        mock_save.assert_called_once()
        mock_send.assert_called_once()
        reply_text = mock_send.call_args[0][2]
        self.assertIn("Data Analyst", reply_text)
        self.assertIn("Etisalat", reply_text)

    @patch("core.telegram_bot.send_message")
    @patch("core.telegram_bot.send_chat_action")
    @patch("core.telegram_bot.scrape_job_from_url")
    @patch("core.telegram_bot.save_or_update_job")
    def test_process_message_with_scholarship_tag(self, mock_save, mock_scrape, mock_action, mock_send):
        mock_scrape.return_value = {
            "job_id": "schol_1",
            "title": "Data Science Master's Fellowship",
            "company": "DAAD",
            "location": "Munich, Germany",
            "job_type": "Scholarship",
            "relevance_score": 85.0
        }
        mock_save.return_value = ({
            "job_id": "schol_1",
            "title": "Data Science Master's Fellowship",
            "company": "DAAD",
            "location": "Munich, Germany",
            "job_type": "Scholarship",
            "relevance_score": 85.0
        }, True)

        msg = {
            "chat": {"id": 12345678},
            "from": {"id": 12345678, "username": "testuser"},
            "text": "#scholarship Check this DAAD grant: https://daad.de/study/grant"
        }

        process_message("fake_token", msg, allowed_chat_id="12345678")

        mock_scrape.assert_called_once_with(url="https://daad.de/study/grant", scraper_type="auto", is_scholarship=True)
        mock_send.assert_called_once()
        reply_text = mock_send.call_args[0][2]
        self.assertIn("Scholarship Saved!", reply_text)
        self.assertIn("DAAD", reply_text)

    @patch("core.telegram_bot.send_message")
    def test_security_unauthorized_chat_id(self, mock_send):
        msg = {
            "chat": {"id": 99999999},  # Intruder / stranger
            "from": {"id": 99999999, "username": "stranger"},
            "text": "https://linkedin.com/jobs/view/123456"
        }

        # Allowed is 12345678, but sender is 99999999
        process_message("fake_token", msg, allowed_chat_id="12345678")

        mock_send.assert_called_once()
        reply_text = mock_send.call_args[0][2]
        self.assertIn("Unauthorized", reply_text)

    def test_record_and_clear_new_jobs(self):
        from core.telegram_bot import record_new_telegram_job, get_and_clear_new_telegram_jobs
        # Clear any prior state
        get_and_clear_new_telegram_jobs()

        record_new_telegram_job("Python Dev")
        record_new_telegram_job("ML Engineer")

        jobs = get_and_clear_new_telegram_jobs()
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs, ["Python Dev", "ML Engineer"])

        # Second call should be empty
        self.assertEqual(get_and_clear_new_telegram_jobs(), [])

    @patch("core.telegram_bot.send_message")
    @patch("core.telegram_bot.get_job_by_url")
    @patch("core.telegram_bot.scrape_job_from_url")
    @patch("core.telegram_bot.save_or_update_job")
    def test_duplicate_job_url_skipped(self, mock_save, mock_scrape, mock_get_url, mock_send):
        mock_get_url.return_value = {
            "job_id": "test_existing",
            "title": "Existing Python Developer",
            "company": "ExistingCorp",
            "relevance_score": 90.0,
            "job_url": "https://linkedin.com/jobs/view/11111"
        }

        msg = {
            "chat": {"id": 12345678},
            "from": {"id": 12345678, "username": "testuser"},
            "text": "https://linkedin.com/jobs/view/11111"
        }

        results = process_message("fake_token", msg, allowed_chat_id="12345678")

        # Must NOT scrape and must NOT save or rescore
        mock_scrape.assert_not_called()
        mock_save.assert_not_called()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "duplicate")

        mock_send.assert_called_once()
        reply_text = mock_send.call_args[0][2]
        self.assertIn("Already in Database", reply_text)
        self.assertIn("Not rescored or re-added", reply_text)

    @patch("core.telegram_bot.send_message")
    def test_batch_summary_reply(self, mock_send):
        from core.telegram_bot import send_summary_reply

        results = [
            {"status": "added", "title": "Senior Python Engineer", "company": "_VOIS", "score": 89.0},
            {"status": "added", "title": "ML Engineer", "company": "Etisalat", "score": 84.0},
            {"status": "duplicate", "title": "Data Analyst", "company": "Orange"}
        ]

        send_summary_reply("fake_token", "12345678", results)

        mock_send.assert_called_once()
        reply_text = mock_send.call_args[0][2]
        parse_mode = mock_send.call_args[1].get("parse_mode")
        self.assertEqual(parse_mode, "HTML")
        self.assertIn("Finished Processing 3 Queued Jobs!", reply_text)
        self.assertIn("Added 2 New Roles", reply_text)
        self.assertIn("1 Repeated Job Skipped (Already in Database)", reply_text)
        self.assertIn("Senior Python Engineer", reply_text)
        self.assertIn("_VOIS", reply_text)
        self.assertIn("Data Analyst", reply_text)

    def test_html_escape(self):
        from core.telegram_bot import html_escape
        self.assertEqual(html_escape("Python <Developer> & AI"), "Python &lt;Developer&gt; &amp; AI")
        self.assertEqual(html_escape("_VOIS"), "_VOIS")
        self.assertEqual(html_escape(None), "")

    @patch("core.telegram_bot.send_summary_reply")
    @patch("core.telegram_bot.requests.get")
    @patch("core.telegram_bot.process_message")
    def test_sync_queued_telegram_jobs(self, mock_process, mock_get, mock_send_summary):
        from core.telegram_bot import sync_queued_telegram_jobs

        # Mock Telegram getUpdates response with 2 updates
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "ok": True,
            "result": [
                {
                    "update_id": 101,
                    "message": {
                        "chat": {"id": 12345678},
                        "text": "https://linkedin.com/jobs/view/101"
                    }
                },
                {
                    "update_id": 102,
                    "message": {
                        "chat": {"id": 12345678},
                        "text": "https://linkedin.com/jobs/view/102"
                    }
                }
            ]
        }
        # First call returns 2 updates, second call returns empty (end of backlog)
        empty_resp = MagicMock()
        empty_resp.status_code = 200
        empty_resp.json.return_value = {"ok": True, "result": []}
        mock_get.side_effect = [mock_resp, empty_resp]

        mock_process.side_effect = [
            [{"status": "added", "title": "Dev 1", "company": "Co 1", "score": 90}],
            [{"status": "duplicate", "title": "Dev 2", "company": "Co 2", "score": 85}]
        ]

        result = sync_queued_telegram_jobs(bot_token="test_token", allowed_chat_id="12345678")

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["jobs"], ["Dev 1"])
        self.assertEqual(result["duplicates"], 1)
        self.assertEqual(result["status"], "success")

        # Consolidated single summary sent
        mock_send_summary.assert_called_once()

    @patch("core.telegram_bot.send_message")
    @patch("core.telegram_bot.send_chat_action")
    @patch("core.telegram_bot.scrape_job_from_url")
    @patch("core.telegram_bot.save_or_update_job")
    def test_process_message_with_liked_tag(self, mock_save, mock_scrape, mock_action, mock_send):
        mock_scrape.return_value = {
            "job_id": "liked_1",
            "title": "AI Engineer",
            "company": "Instabug",
            "location": "Cairo",
            "relevance_score": 92.0
        }
        mock_save.return_value = ({
            "job_id": "liked_1",
            "title": "AI Engineer",
            "company": "Instabug",
            "location": "Cairo",
            "status": "liked",
            "relevance_score": 92.0
        }, True)

        msg = {
            "chat": {"id": 12345678},
            "from": {"id": 12345678, "username": "testuser"},
            "text": "/liked Check this favorite role: https://instabug.com/jobs/ai"
        }

        process_message("fake_token", msg, allowed_chat_id="12345678")

        mock_scrape.assert_called_once()
        save_call_job_dict = mock_save.call_args[0][0]
        self.assertEqual(save_call_job_dict["status"], "liked")
        mock_send.assert_called_once()
        reply_text = mock_send.call_args[0][2]
        self.assertIn("Liked!", reply_text)

    @patch("core.telegram_bot.send_message")
    @patch("core.telegram_bot.send_chat_action")
    @patch("core.telegram_bot.scrape_job_from_url")
    @patch("core.telegram_bot.save_or_update_job")
    def test_process_message_with_applied_tag(self, mock_save, mock_scrape, mock_action, mock_send):
        mock_scrape.return_value = {
            "job_id": "applied_1",
            "title": "Data Scientist",
            "company": "Vodafone",
            "location": "Cairo",
            "relevance_score": 95.0
        }
        mock_save.return_value = ({
            "job_id": "applied_1",
            "title": "Data Scientist",
            "company": "Vodafone",
            "location": "Cairo",
            "status": "liked",
            "is_applied": 1,
            "relevance_score": 95.0
        }, True)

        msg = {
            "chat": {"id": 12345678},
            "from": {"id": 12345678, "username": "testuser"},
            "text": "#applied Just submitted my CV: https://vodafone.com/jobs/ds"
        }

        process_message("fake_token", msg, allowed_chat_id="12345678")

        mock_scrape.assert_called_once()
        save_call_job_dict = mock_save.call_args[0][0]
        self.assertEqual(save_call_job_dict["status"], "liked")
        self.assertEqual(save_call_job_dict["is_applied"], 1)
        mock_send.assert_called_once()
        reply_text = mock_send.call_args[0][2]
        self.assertIn("Applied!", reply_text)

    @patch("core.telegram_bot.send_message")
    @patch("core.telegram_bot.send_chat_action")
    @patch("core.telegram_bot.scrape_job_from_url")
    @patch("core.telegram_bot.delete_job_by_id")
    @patch("core.telegram_bot.save_or_update_job")
    def test_process_message_with_zero_score_pruned(self, mock_save, mock_delete, mock_scrape, mock_action, mock_send):
        mock_scrape.return_value = {
            "job_id": "data analyst|makan",
            "title": "Data Analyst",
            "company": "MAKAN",
            "location": "Riyadh, Saudi Arabia",
            "relevance_score": 0.0,
            "job_type": "Full-time"
        }

        msg = {
            "chat": {"id": 12345678},
            "from": {"id": 12345678, "username": "testuser"},
            "text": "https://lnkd.in/p/eDkFRKq4"
        }

        results = process_message("fake_token", msg, allowed_chat_id="12345678")

        mock_scrape.assert_called_once()
        # Must NOT save the 0-score pending job
        mock_save.assert_not_called()
        mock_delete.assert_called_once_with("data analyst|makan")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "pruned")
        mock_send.assert_called_once()
        reply_text = mock_send.call_args[0][2]
        self.assertIn("Pruned", reply_text)
        self.assertIn("0%", reply_text)


if __name__ == "__main__":
    unittest.main()
