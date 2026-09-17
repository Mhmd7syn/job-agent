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
    save_job, save_dropped_jobs, is_job_seen, get_jobs_by_status,
    cleanup_old_jobs, save_or_update_job, get_job_by_url, init_db
)
from core.scorer import rescore_all_jobs


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

    def test_save_dropped_jobs_records_link_and_status_filtered(self):
        records = [
            {
                "job_id": "dropped_1",
                "job_url": "https://example.com/job/accountant",
                "title": "Senior Accountant",
                "company": "Finance Corp",
                "site": "wuzzuf",
                "date_posted": "2026-09-10"
            }
        ]
        count = save_dropped_jobs(records)
        self.assertEqual(count, 1)

        # is_job_seen must return True to avoid re-scraping
        self.assertTrue(is_job_seen("https://example.com/job/accountant"))

        # Raw DB check: status must be 'filtered', description empty
        conn = sqlite3.connect(self.test_db)
        cursor = conn.cursor()
        cursor.execute("SELECT job_id, status, description, relevance_score FROM jobs WHERE job_url = ?", ("https://example.com/job/accountant",))
        row = cursor.fetchone()
        conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row[0], "dropped_1")
        self.assertEqual(row[1], "filtered")
        self.assertEqual(row[2], "")
        self.assertEqual(row[3], 0)

        # Verify GUI query does NOT return 'filtered' jobs
        gui_jobs = get_jobs_by_status(['pending', 'liked', 'not_related'])
        self.assertEqual(len(gui_jobs), 0)

    def test_save_dropped_jobs_does_not_overwrite_existing_pending(self):
        # Insert a real pending job first
        save_job({
            "job_id": "job_real",
            "job_url": "https://example.com/job/real",
            "title": "Junior Python Dev",
            "company": "Tech",
            "status": "pending",
            "description": "Great python role",
            "relevance_score": 75
        })

        # Attempt to save dropped job with same job_id/url
        save_dropped_jobs([{
            "job_id": "job_real",
            "job_url": "https://example.com/job/real",
            "title": "Junior Python Dev",
            "company": "Tech"
        }])

        conn = sqlite3.connect(self.test_db)
        cursor = conn.cursor()
        cursor.execute("SELECT status, relevance_score, description FROM jobs WHERE job_id = 'job_real'")
        row = cursor.fetchone()
        conn.close()

        # Must preserve pending status and score
        self.assertEqual(row[0], "pending")
        self.assertEqual(row[1], 75)
        self.assertEqual(row[2], "Great python role")

    def test_cleanup_old_jobs_removes_aged_filtered_records(self):
        # 100 days old dropped job
        old_date = (datetime.now() - timedelta(days=100)).strftime("%Y-%m-%d")
        old_timestamp = (datetime.now() - timedelta(days=100)).isoformat()
        
        # 10 days old dropped job
        recent_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        recent_timestamp = (datetime.now() - timedelta(days=10)).isoformat()

        conn = sqlite3.connect(self.test_db)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO jobs (job_id, title, company, job_url, date_posted, timestamp, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, ("old_job", "Old Accounting", "Old Corp", "https://example.com/old", old_date, old_timestamp, "filtered"))
        cursor.execute("""
            INSERT INTO jobs (job_id, title, company, job_url, date_posted, timestamp, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, ("recent_job", "Recent Sales", "Recent Corp", "https://example.com/recent", recent_date, recent_timestamp, "filtered"))
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

    def test_save_jobs_to_db_partitions_and_retains_negative_scores(self):
        df_data = [
            {
                # Job 1: Non-technical (fails preliminary stage 2 -> base_score = 0)
                "title": "Office Administrator",
                "company": "Corp A",
                "job_url": "https://example.com/admin",
                "description": "Answering calls and filing paperwork.",
                "job_type": "Full Time",
                "location": "Cairo",
                "date_posted": datetime.now().strftime("%Y-%m-%d"),
                "site": "wuzzuf"
            },
            {
                # Job 2: Valid technical match, but old (relevance_score <= 0 due to age penalty)
                "title": "Junior Python Developer",
                "company": "Tech Corp",
                "job_url": "https://example.com/python-old",
                "description": "Looking for python and pytorch developer.",
                "job_type": "Full Time",
                "location": "Cairo",
                "date_posted": (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d"),
                "site": "wuzzuf"
            },
            {
                # Job 3: Fresh valid technical match (base_score > 0, relevance_score > 0)
                "title": "Junior AI Engineer",
                "company": "AI Labs",
                "job_url": "https://example.com/ai-fresh",
                "description": "Looking for python and machine learning skills.",
                "job_type": "Full Time",
                "location": "Cairo",
                "date_posted": datetime.now().strftime("%Y-%m-%d"),
                "site": "linkedin"
            }
        ]

        df = pd.DataFrame(df_data)

        from scrapers.link_scraper import _make_job_id
        from core.scorer import calculate_score, load_latest_config

        _config = load_latest_config()

        df['is_remote'] = False
        df['job_id'] = df.apply(lambda r: _make_job_id(r['title'], r['company']), axis=1)

        df['base_score'] = df.apply(lambda r: calculate_score(r.to_dict(), config=_config, apply_date_penalty=False), axis=1)
        is_schol_mask = (df['job_type'] == 'Scholarship') | (df.get('is_scholarship', False) == True)

        passed_mask = (df['base_score'] > 0) | is_schol_mask
        dropped_df = df[~passed_mask]
        valid_df = df[passed_mask].copy()

        self.assertEqual(len(dropped_df), 1)  # Office Administrator
        self.assertEqual(len(valid_df), 2)    # Old Python + Fresh AI

        save_dropped_jobs(dropped_df.to_dict('records'))

        valid_df['relevance_score'] = valid_df.apply(
            lambda r: calculate_score(r.to_dict(), config=_config, apply_date_penalty=True), axis=1
        )

        for _, row in valid_df.iterrows():
            save_job(row.to_dict())

        # Check DB:
        # Admin is filtered
        self.assertTrue(is_job_seen("https://example.com/admin"))
        # Old Python is in DB with pending status, even if score <= 0
        old_py_job = get_job_by_url("https://example.com/python-old")
        self.assertIsNotNone(old_py_job)
        self.assertEqual(old_py_job['status'], "pending")
        self.assertIn("python", old_py_job['description'])

        # Fresh AI is in DB with pending status
        fresh_ai_job = get_job_by_url("https://example.com/ai-fresh")
        self.assertIsNotNone(fresh_ai_job)
        self.assertEqual(fresh_ai_job['status'], "pending")

        # GUI query returns both valid jobs, but NOT the administrator
        gui_jobs = get_jobs_by_status(['pending', 'liked', 'not_related'])
        gui_urls = [j['job_url'] for j in gui_jobs]
        self.assertIn("https://example.com/python-old", gui_urls)
        self.assertIn("https://example.com/ai-fresh", gui_urls)
        self.assertNotIn("https://example.com/admin", gui_urls)

    def test_save_or_update_job_saves_score_zero_or_negative(self):
        # Test manual addition: a job with score <= 0 must be preserved
        job_data = {
            "job_id": "manual_zero_score",
            "job_url": "https://example.com/manual-test",
            "title": "Unrelated Tech Role",
            "company": "Some Company",
            "relevance_score": -10,
            "status": "pending",
            "description": "Some details"
        }
        saved, is_new = save_or_update_job(job_data, force_pending=True)
        self.assertTrue(is_new)
        self.assertEqual(saved["job_id"], "manual_zero_score")
        self.assertEqual(saved["relevance_score"], -10)
        self.assertEqual(saved["status"], "pending")

        # Confirm it exists in DB
        fetched = get_job_by_url("https://example.com/manual-test")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["relevance_score"], -10)


if __name__ == "__main__":
    unittest.main()
