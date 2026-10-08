import os
import sys
import unittest
from datetime import date, datetime, timedelta

# Ensure project root is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

import pandas as pd
from unittest.mock import patch
from core import database
from core.database import init_db, is_job_seen, get_jobs_by_status
from core.job_utils import (
    make_job_id,
    clean_location,
    extract_location_and_setup,
    normalize_job_type,
    normalize_is_remote,
    extract_company_from_desc,
    normalize_company,
    parse_job_date,
    normalize_job_dict,
    score_job_dict,
    process_scraped_batch
)


class TestJobUtils(unittest.TestCase):
    def test_clean_location(self):
        # Prefixes stripped
        self.assertEqual(clean_location("On-site - Egypt - Cairo"), "Egypt - Cairo")
        self.assertEqual(clean_location("Onsite - Cairo"), "Cairo")
        self.assertEqual(clean_location("Remote - United States"), "United States")
        self.assertEqual(clean_location("Hybrid - Cairo, Egypt"), "Cairo, Egypt")
        self.assertEqual(clean_location("عن بعد - القاهرة"), "القاهرة")

        # Standalone location without delimiter preserved
        self.assertEqual(clean_location("Remote"), "Remote")
        self.assertEqual(clean_location("On-site"), "On-site")
        self.assertEqual(clean_location("Cairo, Egypt"), "Cairo, Egypt")
        self.assertEqual(clean_location(""), "")

    def test_extract_location_and_setup(self):
        loc, setup = extract_location_and_setup("On-site - Egypt - Cairo")
        self.assertEqual(loc, "Egypt - Cairo")
        self.assertEqual(setup, "On-site")

        loc, setup = extract_location_and_setup("Remote - Cairo")
        self.assertEqual(loc, "Cairo")
        self.assertEqual(setup, "Remote")

        loc, setup = extract_location_and_setup("Hybrid - Cairo, Egypt")
        self.assertEqual(loc, "Cairo, Egypt")
        self.assertEqual(setup, "Hybrid")

        loc, setup = extract_location_and_setup("Cairo, Egypt", raw_is_remote=True)
        self.assertEqual(loc, "Cairo, Egypt")
        self.assertEqual(setup, "Remote")

    def test_make_job_id_deterministic(self):
        id1 = make_job_id("Junior Python Developer", "Vodafone Egypt")
        id2 = make_job_id("junior python developer!", "Vodafone, Egypt.")
        self.assertEqual(id1, "junior python developer|vodafone egypt")
        self.assertEqual(id1, id2)

    def test_make_job_id_fallback_hash_for_short_names(self):
        short_id = make_job_id("", "", "https://example.com/job/123")
        self.assertTrue(short_id.startswith("job_"))
        self.assertGreaterEqual(len(short_id), 8)

    def test_normalize_job_type(self):
        # Scholarships
        self.assertEqual(normalize_job_type(is_scholarship=True), "Scholarship")
        self.assertEqual(normalize_job_type("", title="DAAD Scholarship 2026"), "Scholarship")
        self.assertEqual(normalize_job_type("", desc="فرصة للحصول على منحة دراسية ممولة"), "Scholarship")

        # Internships
        self.assertEqual(normalize_job_type("Intern"), "Internship")
        self.assertEqual(normalize_job_type("", title="Software Engineering Intern"), "Internship")
        self.assertEqual(normalize_job_type("", desc="Looking for a graduate trainee"), "Internship")

        # Part-time
        self.assertEqual(normalize_job_type("Part Time"), "Part-time")
        self.assertEqual(normalize_job_type("", desc="العمل بنظام دوام جزئي"), "Part-time")

        # Contract
        self.assertEqual(normalize_job_type("freelance"), "Contract")
        self.assertEqual(normalize_job_type("", desc="عقد محدد المدة"), "Contract")

        # Full-time
        self.assertEqual(normalize_job_type("full-time"), "Full-time")
        self.assertEqual(normalize_job_type("", desc="وظيفة دوام كامل"), "Full-time")

        # Not specified
        self.assertEqual(normalize_job_type(""), "Not specified")
        self.assertEqual(normalize_job_type("nan"), "Not specified")

    def test_normalize_is_remote(self):
        # Explicit flag
        self.assertTrue(normalize_is_remote(raw_is_remote=True))
        self.assertTrue(normalize_is_remote(raw_is_remote="true"))

        # English keywords
        self.assertTrue(normalize_is_remote(location="Remote", title="Python Dev"))
        self.assertTrue(normalize_is_remote(location="Cairo", title="Remote AI Engineer"))
        self.assertTrue(normalize_is_remote(location="Cairo", desc="This is a work from home role"))
        self.assertTrue(normalize_is_remote(location="Cairo", desc="WFH available"))

        # Arabic keywords
        self.assertTrue(normalize_is_remote(location="القاهرة", desc="العمل عن بعد بالكامل"))
        self.assertTrue(normalize_is_remote(location="مصر", title="مطور برمجيات - العمل من المنزل"))

        # On-site
        self.assertFalse(normalize_is_remote(location="Cairo, Egypt", title="Onsite AI Engineer", desc="Must report to office daily"))

    def test_normalize_company_and_extraction(self):
        # Known company
        self.assertEqual(normalize_company("Google"), "Google")

        # Confidential with regex match
        desc_with_about = "About TechWave Solutions is a leading AI software company founded in 2020."
        extracted = normalize_company("Confidential", desc=desc_with_about)
        self.assertEqual(extracted, "TechWave Solutions")

        desc_with_hiring = "Leading Tech Corp is seeking a talented junior engineer for our team."
        extracted_hiring = normalize_company("Unknown", desc=desc_with_hiring)
        self.assertEqual(extracted_hiring, "Leading Tech Corp")

    def test_parse_job_date(self):
        today = date.today()
        # ISO string
        self.assertEqual(parse_job_date("2026-05-10"), "2026-05-10")

        # Datetime object
        dt = datetime(2026, 4, 15, 12, 0, 0)
        self.assertEqual(parse_job_date(dt), "2026-04-15")

        # Relative days
        self.assertEqual(parse_job_date("3 days ago"), (today - timedelta(days=3)).isoformat())
        self.assertEqual(parse_job_date("منذ 3 أيام"), (today - timedelta(days=3)).isoformat())

        # Relative weeks
        self.assertEqual(parse_job_date("2 weeks ago"), (today - timedelta(days=14)).isoformat())

        # Relative months
        self.assertEqual(parse_job_date("1 month ago"), (today - timedelta(days=30)).isoformat())

        # Yesterday / Today
        self.assertEqual(parse_job_date("yesterday"), (today - timedelta(days=1)).isoformat())
        self.assertEqual(parse_job_date("أمس"), (today - timedelta(days=1)).isoformat())
        self.assertEqual(parse_job_date("today"), today.isoformat())
        self.assertEqual(parse_job_date("اليوم"), today.isoformat())

    def test_normalize_job_dict(self):
        raw = {
            "title": "Junior Python Developer",
            "company": "Vodafone",
            "location": "Cairo, Egypt",
            "job_url": "https://example.com/job/1",
            "job_type": "Full Time",
            "date_posted": "3 days ago",
            "site": "wuzzuf",
            "description": "Python, SQL, and machine learning required.",
            "is_remote": False
        }
        norm = normalize_job_dict(raw)
        self.assertEqual(norm["job_id"], "junior python developer|vodafone")
        self.assertEqual(norm["job_type"], "Full-time")
        self.assertEqual(norm["date_posted"], (date.today() - timedelta(days=3)).isoformat())
        self.assertEqual(norm["site"], "wuzzuf")
        self.assertFalse(norm["is_remote"])
        self.assertEqual(norm["status"], "pending")
        self.assertEqual(norm["is_applied"], 0)

        # Test location prefix stripping and setup detection in normalize_job_dict
        raw_onsite = {
            "title": "Business Data Analyst",
            "company": "Wuzzuf",
            "location": "On-site - Egypt - Cairo",
            "job_url": "https://example.com/job/2",
            "job_type": "Internship"
        }
        norm_onsite = normalize_job_dict(raw_onsite)
        self.assertEqual(norm_onsite["location"], "Egypt - Cairo")
        self.assertEqual(norm_onsite["workplace_setup"], "On-site")
        self.assertEqual(norm_onsite["job_type"], "Internship")
        self.assertFalse(norm_onsite["is_remote"])

        raw_remote = {
            "title": "Data Analyst",
            "company": "Tech",
            "location": "Remote - Egypt - Cairo",
            "job_url": "https://example.com/job/3",
            "job_type": "Full-time"
        }
        norm_remote = normalize_job_dict(raw_remote)
        self.assertEqual(norm_remote["location"], "Egypt - Cairo")
        self.assertEqual(norm_remote["workplace_setup"], "Remote")
        self.assertEqual(norm_remote["job_type"], "Full-time")
        self.assertTrue(norm_remote["is_remote"])

    def test_score_job_dict(self):
        job = {
            "job_id": "junior python developer|vodafone",
            "title": "Junior AI Engineer",
            "company": "Vodafone",
            "location": "Cairo, Egypt",
            "job_url": "https://example.com/job/1",
            "job_type": "Full-time",
            "date_posted": date.today().isoformat(),
            "description": "Python, PyTorch, and machine learning required.",
            "is_remote": False
        }
        scored = score_job_dict(job)
        self.assertIn("base_score", scored)
        self.assertIn("relevance_score", scored)
        self.assertGreater(scored["base_score"], 0)
        self.assertGreater(scored["relevance_score"], 0)

    def test_process_scraped_batch_end_to_end(self):
        test_db = os.path.join(BASE_DIR, "output", "test_batch_utils.db")
        with patch.object(database, "DB_PATH", test_db):
            if os.path.exists(test_db):
                os.remove(test_db)
            init_db()

            df_raw = pd.DataFrame([
                {
                    "title": "Accountant",
                    "company": "Finance Corp",
                    "location": "Cairo",
                    "job_url": "https://example.com/acc",
                    "description": "Ledgers and balance sheets",
                    "site": "wuzzuf"
                },
                {
                    "title": "Junior AI Engineer",
                    "company": "AI Labs",
                    "location": "Cairo",
                    "job_url": "https://example.com/ai",
                    "description": "Python, deep learning, PyTorch",
                    "site": "linkedin"
                }
            ])

            saved_df = process_scraped_batch([df_raw])
            self.assertIsNotNone(saved_df)
            self.assertEqual(len(saved_df), 1)  # Only AI engineer is saved as valid job

            # Accountant must be saved as dropped link (filtered)
            self.assertTrue(is_job_seen("https://example.com/acc"))
            # AI Engineer must be in pending jobs
            self.assertTrue(is_job_seen("https://example.com/ai"))

            gui_jobs = get_jobs_by_status(['pending', 'liked', 'not_related'])
            self.assertEqual(len(gui_jobs), 1)
            self.assertEqual(gui_jobs[0]["title"], "Junior AI Engineer")

            if os.path.exists(test_db):
                try:
                    os.remove(test_db)
                except Exception:
                    pass


if __name__ == "__main__":
    unittest.main()
