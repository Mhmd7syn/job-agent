import os
import sys
import sqlite3
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

# Ensure project root is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

import pandas as pd
from core import database
from core.database import (
    save_job, is_job_seen, get_jobs_by_status,
    cleanup_old_jobs, save_or_update_job, get_job_by_url, init_db
)
from core.job_utils import process_scraped_batch
from core.scorer import rescore_all_jobs, load_latest_config


class TestProblem5DedupRetention(unittest.TestCase):
    def setUp(self):
        # Use a separate test SQLite DB
        self.test_db = os.path.join(BASE_DIR, "output", "test_problem_5.db")
        self.db_patcher = patch.object(database, "DB_PATH", self.test_db)
        self.db_patcher.start()
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
        init_db()

    def tearDown(self):
        self.db_patcher.stop()
        if os.path.exists(self.test_db):
            try:
                os.remove(self.test_db)
            except Exception:
                pass

    def test_zero_score_job_saved_normally_with_full_data_and_seen(self):
        record = {
            "job_id": "accountant_1",
            "job_url": "https://example.com/job/accountant",
            "apply_url": "https://example.com/apply/accountant",
            "title": "Senior Accountant",
            "company": "Finance Corp",
            "location": "Cairo",
            "site": "wuzzuf",
            "description": "General ledger, monthly closing, and financial reports.",
            "date_posted": "2026-09-10",
            "relevance_score": 0.0,
            "status": "pending"
        }
        save_job(record)

        # Both job_url and apply_url must be recognized as seen to prevent re-scraping
        self.assertTrue(is_job_seen("https://example.com/job/accountant"))
        self.assertTrue(is_job_seen("https://example.com/apply/accountant"))

        # DB must retain full metadata, description, and status='pending'
        job = get_job_by_url("https://example.com/job/accountant")
        self.assertIsNotNone(job)
        self.assertEqual(job["job_id"], "accountant_1")
        self.assertEqual(job["status"], "pending")
        self.assertEqual(job["description"], "General ledger, monthly closing, and financial reports.")
        self.assertEqual(job["relevance_score"], 0.0)

    def test_cleanup_old_jobs_removes_aged_records(self):
        old_date = (datetime.now() - timedelta(days=100)).strftime("%Y-%m-%d")
        old_timestamp = (datetime.now() - timedelta(days=100)).isoformat()
        
        recent_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        recent_timestamp = (datetime.now() - timedelta(days=10)).isoformat()

        conn = sqlite3.connect(self.test_db)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO jobs (job_id, title, company, job_url, date_posted, timestamp, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, ("old_job", "Old Accounting", "Old Corp", "https://example.com/old", old_date, old_timestamp, "pending"))
        cursor.execute("""
            INSERT INTO jobs (job_id, title, company, job_url, date_posted, timestamp, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, ("recent_job", "Recent Sales", "Recent Corp", "https://example.com/recent", recent_date, recent_timestamp, "pending"))
        conn.commit()
        conn.close()

        self.assertTrue(is_job_seen("https://example.com/old"))
        self.assertTrue(is_job_seen("https://example.com/recent"))

        # Run retention cleanup for 90 days
        deleted = cleanup_old_jobs(days=90)
        self.assertEqual(deleted, 1)

        # Old job must be removed, recent job preserved
        self.assertFalse(is_job_seen("https://example.com/old"))
        self.assertTrue(is_job_seen("https://example.com/recent"))

    def test_process_scraped_batch_preserves_all_data_and_enables_rescoring(self):
        df_data = [
            {
                # Job 1: Non-technical role with initial score 0
                "title": "Office Administrator",
                "company": "Corp A",
                "job_url": "https://example.com/admin",
                "apply_url": "https://example.com/apply-admin",
                "description": "Answering calls, managing office schedules, and filing paperwork.",
                "job_type": "Full Time",
                "location": "Cairo",
                "date_posted": datetime.now().strftime("%Y-%m-%d"),
                "site": "wuzzuf"
            },
            {
                # Job 2: Valid technical match
                "title": "Junior Python Developer",
                "company": "Tech Corp",
                "job_url": "https://example.com/python-dev",
                "apply_url": "https://example.com/apply-python",
                "description": "Looking for python and pytorch developer with backend skills.",
                "job_type": "Full Time",
                "location": "Cairo",
                "date_posted": datetime.now().strftime("%Y-%m-%d"),
                "site": "wuzzuf"
            }
        ]

        df = pd.DataFrame(df_data)
        saved_df = process_scraped_batch([df])
        self.assertIsNotNone(saved_df)
        self.assertEqual(len(saved_df), 2)  # All jobs are saved

        # Verify both jobs are in DB with full data and status='pending'
        admin_job = get_job_by_url("https://example.com/admin")
        self.assertIsNotNone(admin_job)
        self.assertEqual(admin_job["status"], "pending")
        self.assertEqual(admin_job["relevance_score"], 0.0)
        self.assertEqual(admin_job["description"], "Answering calls, managing office schedules, and filing paperwork.")
        self.assertEqual(admin_job["apply_url"], "https://example.com/apply-admin")

        python_job = get_job_by_url("https://example.com/python-dev")
        self.assertIsNotNone(python_job)
        self.assertGreater(python_job["relevance_score"], 0)

        # Both URLs are seen to prevent re-scraping
        self.assertTrue(is_job_seen("https://example.com/admin"))
        self.assertTrue(is_job_seen("https://example.com/apply-admin"))

        # Now simulate preference change: user adds "Office Administrator" to search terms & skills
        current_cfg = load_latest_config()
        updated_cfg = dict(current_cfg)
        updated_cfg["SEARCH_TERMS"] = list(current_cfg.get("SEARCH_TERMS", [])) + ["Office Administrator"]
        updated_cfg["RESUME_KEYWORDS"] = list(current_cfg.get("RESUME_KEYWORDS", [])) + ["filing paperwork", "office schedules"]

        from core import scorer
        with patch.object(scorer, "DB_PATH", self.test_db), \
             patch("core.scorer.load_latest_config", return_value=updated_cfg):
            rescore_all_jobs()

        # Admin job now has higher score because its full description was preserved!
        rescored_admin = get_job_by_url("https://example.com/admin")
        self.assertGreater(rescored_admin["relevance_score"], 0)

    def test_save_or_update_job_saves_score_zero_or_negative(self):
        job_data = {
            "job_id": "manual_zero_score",
            "job_url": "https://example.com/manual-test",
            "title": "Unrelated Tech Role",
            "company": "Some Company",
            "relevance_score": 0.0,
            "status": "pending",
            "description": "Some details"
        }
        saved, is_new = save_or_update_job(job_data, force_pending=True)
        self.assertTrue(is_new)
        self.assertEqual(saved["job_id"], "manual_zero_score")
        self.assertEqual(saved["relevance_score"], 0.0)
        self.assertEqual(saved["status"], "pending")

        # Confirm it exists in DB
        fetched = get_job_by_url("https://example.com/manual-test")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["relevance_score"], 0.0)

    def test_refresh_republished_job_updates_date_and_url_preserving_description(self):
        from core.database import is_job_id_seen, refresh_republished_job
        old_date = (datetime.now() - timedelta(days=45)).strftime("%Y-%m-%d")
        new_date = datetime.now().strftime("%Y-%m-%d")

        job_data = {
            "job_id": "python_corp",
            "job_url": "https://example.com/job/v1",
            "title": "Python Developer",
            "company": "Tech Corp",
            "relevance_score": 50.0,
            "status": "pending",
            "description": "Deep Python, FastAPI and database engineering.",
            "date_posted": old_date
        }
        save_job(job_data)

        # Check job_id seen
        self.assertTrue(is_job_id_seen("python_corp"))
        self.assertFalse(is_job_id_seen("unknown_role"))

        # Republished role encountered with new link & today's date
        refreshed = refresh_republished_job("python_corp", job_url="https://example.com/job/v2", date_posted=new_date)
        self.assertTrue(refreshed)

        # Confirm DB updated date and url, preserving full description
        updated_job = get_job_by_url("https://example.com/job/v2")
        self.assertIsNotNone(updated_job)
        self.assertEqual(updated_job["job_url"], "https://example.com/job/v2")
        self.assertEqual(updated_job["date_posted"], new_date)
        self.assertEqual(updated_job["description"], "Deep Python, FastAPI and database engineering.")


if __name__ == "__main__":
    unittest.main()
