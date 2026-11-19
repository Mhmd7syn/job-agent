import pytest
from unittest.mock import patch, MagicMock
import pandas as pd
import sqlite3

from scrapers.common import (
    get_scraped_site_from_url,
    reinject_scraped_job,
    SCRAPED_PLATFORMS,
)
from core.job_utils import process_scraped_batch
from core import database
from core.database import init_db, save_job, get_job_by_url


class TestGetScrapedSiteFromUrl:
    def test_target_platforms(self):
        assert get_scraped_site_from_url("https://www.linkedin.com/jobs/view/12345678") == "linkedin"
        assert get_scraped_site_from_url("https://lnkd.in/test123") == "linkedin"
        assert get_scraped_site_from_url("https://www.bayt.com/en/egypt/jobs/ai-engineer-75423284/") == "bayt"
        assert get_scraped_site_from_url("https://wuzzuf.net/jobs/p/123-python-dev") == "wuzzuf"
        assert get_scraped_site_from_url("https://www.glassdoor.com/job-listing/1234") == "glassdoor"
        assert get_scraped_site_from_url("https://www.indeed.com/viewjob?jk=abcdef") == "indeed"

    def test_non_target_platforms(self):
        assert get_scraped_site_from_url("https://www.naukrigulf.com/job/123") is None
        assert get_scraped_site_from_url("https://careers.google.com/jobs/123") is None
        assert get_scraped_site_from_url("https://boards.greenhouse.io/company/jobs/123") is None
        assert get_scraped_site_from_url("") is None
        assert get_scraped_site_from_url(None) is None


class TestReinjectScrapedJob:
    def test_no_apply_url_returns_job_unchanged(self):
        job = {"title": "Python Dev", "site": "linkedin", "job_url": "https://linkedin.com/jobs/view/1"}
        assert reinject_scraped_job(job) == job

    def test_non_scraped_apply_url_returns_job_unchanged(self):
        job = {
            "title": "Python Dev",
            "site": "linkedin",
            "job_url": "https://linkedin.com/jobs/view/1",
            "apply_url": "https://careers.google.com/jobs/1"
        }
        assert reinject_scraped_job(job) == job

    def test_same_platform_apply_url_returns_job_unchanged(self):
        job = {
            "title": "Python Dev",
            "site": "linkedin",
            "job_url": "https://linkedin.com/jobs/view/1",
            "apply_url": "https://www.linkedin.com/jobs/view/1"
        }
        assert reinject_scraped_job(job) == job

    @patch("core.database.save_job")
    def test_discards_job_if_target_already_seen(self, mock_save_job):
        job = {
            "title": "AI Engineer",
            "site": "linkedin",
            "job_url": "https://www.linkedin.com/jobs/view/112233",
            "apply_url": "https://www.bayt.com/en/egypt/jobs/ai-engineer-75423284/"
        }
        mock_seen = MagicMock(return_value=True)

        res = reinject_scraped_job(job, is_job_seen_fn=mock_seen)
        assert res is None

        # Verify old referrer link is stored with score 0
        mock_save_job.assert_called_once()
        saved = mock_save_job.call_args[0][0]
        assert saved["job_url"] == "https://www.linkedin.com/jobs/view/112233"
        assert saved["relevance_score"] == 0

    @patch("core.database.save_job")
    @patch("scrapers.link_scraper.scrape_job_from_url")
    def test_reinjects_and_scrapes_direct_target_job(self, mock_scrape_from_url, mock_save_job):
        job = {
            "title": "AI Engineer",
            "company": "LamdaX",
            "site": "linkedin",
            "job_url": "https://www.linkedin.com/jobs/view/112233",
            "apply_url": "https://www.bayt.com/en/egypt/jobs/ai-engineer-75423284/"
        }
        mock_seen = MagicMock(return_value=False)
        mock_scrape_from_url.return_value = {
            "title": "AI Engineer",
            "company": "LamdaX",
            "location": "Egypt",
            "site": "bayt",
            "job_url": "https://www.bayt.com/en/egypt/jobs/ai-engineer-75423284/",
            "apply_url": "https://www.bayt.com/en/egypt/jobs/ai-engineer-75423284/",
            "description": "Full Bayt job description",
            "job_type": "Full-time",
            "date_posted": "2026-11-16"
        }

        res = reinject_scraped_job(job, is_job_seen_fn=mock_seen)

        assert res is not None
        assert res["site"] == "bayt"
        assert res["job_url"] == "https://www.bayt.com/en/egypt/jobs/ai-engineer-75423284/"
        mock_scrape_from_url.assert_called_once_with("https://www.bayt.com/en/egypt/jobs/ai-engineer-75423284/")

        # Verify old referrer link was marked in DB with score 0
        mock_save_job.assert_called_once()
        saved = mock_save_job.call_args[0][0]
        assert saved["job_url"] == "https://www.linkedin.com/jobs/view/112233"
        assert saved["relevance_score"] == 0

    @patch("scrapers.link_scraper.scrape_job_from_url")
    def test_fallback_to_original_job_when_direct_scrape_fails(self, mock_scrape_from_url):
        job = {
            "title": "AI Engineer",
            "site": "linkedin",
            "job_url": "https://www.linkedin.com/jobs/view/112233",
            "apply_url": "https://www.bayt.com/en/egypt/jobs/ai-engineer-75423284/"
        }
        mock_seen = MagicMock(return_value=False)
        mock_scrape_from_url.side_effect = RuntimeError("Network error")

        res = reinject_scraped_job(job, is_job_seen_fn=mock_seen)
        assert res == job


class TestBatchReinjectIntegration:
    @patch("scrapers.common.reinject_scraped_job")
    @patch("core.database.save_job")
    def test_process_scraped_batch_calls_reinject(self, mock_save_job, mock_reinject):
        mock_reinject.side_effect = lambda j: j

        df = pd.DataFrame([{
            "title": "AI Engineer",
            "company": "LamdaX",
            "site": "linkedin",
            "job_url": "https://www.linkedin.com/jobs/view/112233",
            "apply_url": "https://www.bayt.com/en/egypt/jobs/ai-engineer-75423284/",
            "description": "Short description",
            "date_posted": "2026-11-16"
        }])

        result_df = process_scraped_batch([df])
        assert result_df is not None
        mock_reinject.assert_called_once()


class TestDatabaseSiteSynchronization:
    def test_save_job_updates_site_on_newer_posting(self, tmp_path):
        test_db = str(tmp_path / "test_site_sync.db")
        with patch.object(database, "DB_PATH", test_db):
            init_db()

            # 1. Insert original LinkedIn job
            save_job({
                "job_id": "ai engineer|lamdax",
                "title": "AI Engineer",
                "company": "LamdaX",
                "site": "linkedin",
                "job_url": "https://www.linkedin.com/jobs/view/4484455114",
                "apply_url": "https://www.linkedin.com/jobs/view/4484455114",
                "date_posted": "2026-10-28",
                "relevance_score": 50.0
            })

            job = get_job_by_url("https://www.linkedin.com/jobs/view/4484455114")
            assert job is not None
            assert job["site"] == "linkedin"

            # 2. Re-scraped from Bayt with newer date
            save_job({
                "job_id": "ai engineer|lamdax",
                "title": "AI Engineer",
                "company": "LamdaX",
                "site": "bayt",
                "job_url": "https://www.bayt.com/en/egypt/jobs/ai-engineer-75423284/",
                "apply_url": "https://www.bayt.com/en/egypt/jobs/ai-engineer-75423284/",
                "date_posted": "2026-11-16",
                "relevance_score": 58.0
            })

            updated_job = get_job_by_url("https://www.bayt.com/en/egypt/jobs/ai-engineer-75423284/")
            assert updated_job is not None
            assert updated_job["site"] == "bayt"
            assert updated_job["job_url"] == "https://www.bayt.com/en/egypt/jobs/ai-engineer-75423284/"
            assert updated_job["date_posted"] == "2026-11-16"
