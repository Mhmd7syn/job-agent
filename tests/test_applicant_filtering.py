import unittest
import os
import sqlite3
import tempfile
import urllib.parse
from bs4 import BeautifulSoup
from unittest.mock import patch, MagicMock

from scrapers.common import extract_applicant_count
from core.job_utils import normalize_job_dict
from core import scorer
from core import database


class TestApplicantParser(unittest.TestCase):
    """Test suite verifying parser resilience across applicant count formats."""

    def test_standard_english_counts(self):
        self.assertEqual(extract_applicant_count("1 applicant"), 1)
        self.assertEqual(extract_applicant_count("23 applicants"), 23)
        self.assertEqual(extract_applicant_count("45 applicants"), 45)
        self.assertEqual(extract_applicant_count("14 applicants for 1 open position"), 14)
        self.assertEqual(extract_applicant_count("1,245 applicants"), 1245)

    def test_bound_and_quantifier_phrases(self):
        self.assertEqual(extract_applicant_count("Under 10 applicants"), 10)
        self.assertEqual(extract_applicant_count("Less than 50 applicants"), 50)
        self.assertEqual(extract_applicant_count("Be among the first 25 applicants"), 25)
        self.assertEqual(extract_applicant_count("Over 200 applicants"), 200)
        self.assertEqual(extract_applicant_count("More than 100 applicants"), 100)
        self.assertEqual(extract_applicant_count("50+ applicants"), 50)
        self.assertEqual(extract_applicant_count("+25 applicants"), 25)

    def test_prefix_formats(self):
        self.assertEqual(extract_applicant_count("Applicants: 14"), 14)
        self.assertEqual(extract_applicant_count("Applicants - 7"), 7)
        self.assertEqual(extract_applicant_count("applicants 32"), 32)
        self.assertEqual(extract_applicant_count("متقدمين: 14"), 14)

    def test_zero_applicants_indicators(self):
        self.assertEqual(extract_applicant_count("No applicants yet"), 0)
        self.assertEqual(extract_applicant_count("Be the first to apply"), 0)
        self.assertEqual(extract_applicant_count("كن أول من يتقدم"), 0)
        self.assertEqual(extract_applicant_count("لا يوجد متقدمين"), 0)

    def test_arabic_phrases_and_numerals(self):
        self.assertEqual(extract_applicant_count("14 متقدم"), 14)
        self.assertEqual(extract_applicant_count("١٤ متقدم"), 14)
        self.assertEqual(extract_applicant_count("أقل من 10 متقدمين"), 10)
        self.assertEqual(extract_applicant_count("كن من أول 25 متقدم"), 25)
        self.assertEqual(extract_applicant_count("أكثر من 50 متقدم"), 50)

    def test_resilience_missing_and_malformed(self):
        self.assertIsNone(extract_applicant_count(None))
        self.assertIsNone(extract_applicant_count(""))
        self.assertIsNone(extract_applicant_count("   "))
        self.assertIsNone(extract_applicant_count("Cairo, Egypt"))
        self.assertIsNone(extract_applicant_count("Full Time • Junior"))
        self.assertIsNone(extract_applicant_count("123 Main Road, Building 4"))

    def test_beautifulsoup_input(self):
        soup = BeautifulSoup('<span class="applicant-count">18 applicants</span>', 'html.parser')
        self.assertEqual(extract_applicant_count(soup), 18)


class TestLinkedInQueryFilters(unittest.TestCase):
    """Test suite verifying LinkedIn search query parameters with low-competition filter."""

    @patch("curl_cffi.requests.get")
    def test_guest_api_appends_f_ea_when_enabled(self, mock_get):
        from scrapers.playwright_scraper import scrape_linkedin_guest_api

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body></body></html>"
        mock_get.return_value = mock_resp

        scrape_linkedin_guest_api("python developer", "egypt", results_wanted=1, low_competition=True)
        self.assertTrue(mock_get.called)
        called_url = mock_get.call_args[0][0]
        self.assertIn("f_EA=true", called_url)

    @patch("curl_cffi.requests.get")
    def test_guest_api_omits_f_ea_when_disabled(self, mock_get):
        from scrapers.playwright_scraper import scrape_linkedin_guest_api

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body></body></html>"
        mock_get.return_value = mock_resp

        scrape_linkedin_guest_api("python developer", "egypt", results_wanted=1, low_competition=False)
        self.assertTrue(mock_get.called)
        called_url = mock_get.call_args[0][0]
        self.assertNotIn("f_EA=true", called_url)

    @patch("core.scorer.load_latest_config")
    @patch("curl_cffi.requests.get")
    def test_guest_api_uses_config_default(self, mock_get, mock_config):
        from scrapers.playwright_scraper import scrape_linkedin_guest_api

        mock_config.return_value = {"LOW_COMPETITION_FILTER": True}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body></body></html>"
        mock_get.return_value = mock_resp

        scrape_linkedin_guest_api("python developer", "egypt", results_wanted=1, low_competition=None)
        called_url = mock_get.call_args[0][0]
        self.assertIn("f_EA=true", called_url)


class TestJobUtilsNormalization(unittest.TestCase):
    """Test suite verifying applicant count normalization in job dictionary."""

    def test_normalize_valid_applicant_counts(self):
        job = {"title": "AI Engineer", "num_applicants": 25}
        norm = normalize_job_dict(job)
        self.assertEqual(norm.get("num_applicants"), 25)

        job_str = {"title": "AI Engineer", "num_applicants": "42"}
        norm_str = normalize_job_dict(job_str)
        self.assertEqual(norm_str.get("num_applicants"), 42)

    def test_normalize_invalid_or_missing_applicant_counts(self):
        job_none = {"title": "AI Engineer"}
        self.assertIsNone(normalize_job_dict(job_none).get("num_applicants"))

        job_invalid = {"title": "AI Engineer", "num_applicants": "unspecified"}
        self.assertIsNone(normalize_job_dict(job_invalid).get("num_applicants"))


class TestDatabaseApplicantStorage(unittest.TestCase):
    """Test suite verifying persistence and retrieval of num_applicants in SQLite."""

    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.test_dir.name, "test_jobs.db")
        self.orig_db_path = database.DB_PATH
        database.DB_PATH = self.db_path
        database.init_db()

    def tearDown(self):
        database.DB_PATH = self.orig_db_path
        self.test_dir.cleanup()

    def test_save_and_retrieve_num_applicants(self):
        job = {
            "job_id": "test-job-applicant-1",
            "title": "Machine Learning Engineer",
            "company": "TechCorp",
            "location": "Cairo, Egypt",
            "job_url": "https://example.com/job/1",
            "status": "pending",
            "relevance_score": 85,
            "num_applicants": 17,
        }
        database.save_job(job)

        jobs = database.get_jobs_by_status(["pending"])
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["num_applicants"], 17)

    def test_save_or_update_preserves_num_applicants(self):
        job = {
            "job_id": "test-job-applicant-2",
            "title": "Data Scientist",
            "company": "DataCorp",
            "location": "Remote",
            "job_url": "https://example.com/job/2",
            "status": "pending",
            "relevance_score": 90,
            "num_applicants": 8,
        }
        inserted, is_new = database.save_or_update_job(job)
        self.assertTrue(is_new)
        self.assertEqual(inserted["num_applicants"], 8)

        # Update without overriding num_applicants
        job_update = {
            "job_id": "test-job-applicant-2",
            "job_url": "https://example.com/job/2",
            "relevance_score": 95,
        }
        updated, is_new2 = database.save_or_update_job(job_update)
        self.assertFalse(is_new2)
        self.assertEqual(updated["num_applicants"], 8)


class TestScorerEarlyApplicantBoost(unittest.TestCase):
    """Test suite verifying relevance scoring boost for low-competition postings."""

    def setUp(self):
        self.base_config = {
            "ROLES": [
                {
                    "title": "AI & Machine Learning",
                    "english_terms": ["AI Engineer", "Data Scientist"],
                    "years_experience": 1,
                    "resume_keywords": ["python", "machine learning"],
                }
            ],
            "TARGET_LOCATIONS": ["cairo", "remote"],
            "TARGET_LEVELS": ["Junior"],
            "LEVEL_EXCLUDE": ["Senior"],
            "EARLY_APPLICANT_THRESHOLD": 50,
            "EARLY_APPLICANT_BOOST": 5,
        }

    def test_early_applicant_receives_boost(self):
        job_low = {
            "title": "Junior AI Engineer",
            "description": "Python, machine learning development.",
            "location": "Cairo",
            "company": "Innovate AI",
            "num_applicants": 12,
            "date_posted": "2026-11-24",
        }
        job_high = {
            "title": "Junior AI Engineer",
            "description": "Python, machine learning development.",
            "location": "Cairo",
            "company": "Innovate AI",
            "num_applicants": 120,
            "date_posted": "2026-11-24",
        }
        score_low = scorer.calculate_score(job_low, config=self.base_config, apply_date_penalty=False)
        score_high = scorer.calculate_score(job_high, config=self.base_config, apply_date_penalty=False)

        # Early applicant score should be higher by exactly the boost (+5)
        self.assertEqual(score_low - score_high, 5)

    def test_missing_or_boundary_applicants(self):
        job_none = {
            "title": "Junior AI Engineer",
            "description": "Python, machine learning development.",
            "location": "Cairo",
            "company": "Innovate AI",
            "num_applicants": None,
            "date_posted": "2026-11-24",
        }
        job_exact_50 = {
            "title": "Junior AI Engineer",
            "description": "Python, machine learning development.",
            "location": "Cairo",
            "company": "Innovate AI",
            "num_applicants": 50,
            "date_posted": "2026-11-24",
        }
        score_none = scorer.calculate_score(job_none, config=self.base_config, apply_date_penalty=False)
        score_50 = scorer.calculate_score(job_exact_50, config=self.base_config, apply_date_penalty=False)

        # 50 is not < 50, so no boost; same as None
        self.assertEqual(score_none, score_50)


if __name__ == "__main__":
    unittest.main()
