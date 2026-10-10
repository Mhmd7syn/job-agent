import pytest
from unittest.mock import patch, MagicMock
import pandas as pd

from scrapers.tanqeeb_scraper import (
    scrape_tanqeeb,
    get_scraped_site_from_url,
    fetch_tanqeeb_job_details,
    SCRAPED_PLATFORMS,
)
from scrapers.link_scraper import _scrape_tanqeeb, scrape_job_from_url


class TestTanqeebScrapedPlatforms:
    def test_get_scraped_site_from_url(self):
        # Target scraped platforms
        assert get_scraped_site_from_url("https://www.linkedin.com/jobs/view/4465078516") == "linkedin"
        assert get_scraped_site_from_url("https://lnkd.in/e9xyz") == "linkedin"
        assert get_scraped_site_from_url("https://www.bayt.com/en/egypt/jobs/python-dev-12345/") == "bayt"
        assert get_scraped_site_from_url("https://wuzzuf.net/jobs/p/123-python-engineer") == "wuzzuf"
        assert get_scraped_site_from_url("https://www.glassdoor.com/job-listing/1234") == "glassdoor"
        assert get_scraped_site_from_url("https://eg.indeed.com/viewjob?jk=abcdef") == "indeed"

        # Non-scraped platforms should return None
        assert get_scraped_site_from_url("https://www.naukrigulf.com/job/12345") is None
        assert get_scraped_site_from_url("https://www.gulftalent.com/egypt/jobs/123") is None
        assert get_scraped_site_from_url("https://egypt.tanqeeb.com/jobs/details/123") is None
        assert get_scraped_site_from_url("https://careers.google.com/jobs/results/123") is None
        assert get_scraped_site_from_url("") is None
        assert get_scraped_site_from_url(None) is None


class TestTanqeebLinkReplacement:
    SAMPLE_HTML = """
    <html>
    <body>
      <div class="card">
        <h2><a href="/jobs/details/100-linkedin-job.html">Python Engineer</a></h2>
        <span class="company">Tech Global</span>
        <span class="location">Cairo</span>
        <span class="date">today</span>
      </div>
      <div class="card">
        <h2><a href="/jobs/details/200-naukri-job.html">Data Analyst</a></h2>
        <span class="company">Gulf Solutions</span>
        <span class="location">Giza</span>
        <span class="date">today</span>
      </div>
    </body>
    </html>
    """

    @patch("scrapers.link_scraper.scrape_job_from_url")
    @patch("scrapers.tanqeeb_scraper.is_job_seen")
    @patch("scrapers.tanqeeb_scraper.fetch_tanqeeb_job_details")
    @patch("scrapers.tanqeeb_scraper.fetch_tanqeeb_full_description")
    @patch("scrapers.tanqeeb_scraper.fetch_with_retries")
    def test_replaces_tanqeeb_link_with_scraped_apply_link(
        self, mock_fetch_page, mock_fetch_desc, mock_fetch_details, mock_is_seen, mock_scrape_from_url
    ):
        mock_is_seen.return_value = False

        # Mock search page response
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = self.SAMPLE_HTML.encode("utf-8")
        mock_fetch_page.side_effect = [mock_resp, None]

        # Job 1 points to LinkedIn (one of our scraped websites)
        # Job 2 points to Naukri Gulf (not one of our scraped websites)
        def side_effect_details(url):
            if "100" in url:
                return {
                    "description": "Full description for Python Engineer on LinkedIn",
                    "company": "Tech Global",
                    "apply_url": "https://www.linkedin.com/jobs/view/99887766",
                    "site_name": "LinkedIn"
                }
            elif "200" in url:
                return {
                    "description": "Full description for Data Analyst on Naukri Gulf",
                    "company": "Gulf Solutions",
                    "apply_url": "https://www.naukrigulf.com/data-analyst-jobs-1234",
                    "site_name": "Naukri Gulf"
                }
            return {}

        mock_fetch_details.side_effect = side_effect_details
        mock_fetch_desc.side_effect = lambda u: side_effect_details(u).get("description", "")

        mock_scrape_from_url.return_value = {
            "title": "Python Engineer",
            "company": "Tech Global",
            "location": "Cairo",
            "site": "linkedin",
            "job_url": "https://www.linkedin.com/jobs/view/99887766",
            "apply_url": "https://www.linkedin.com/jobs/view/99887766",
            "description": "Full description for Python Engineer on LinkedIn",
            "job_type": "Full-time",
            "date_posted": "2026-10-09"
        }

        df = scrape_tanqeeb("python", "egypt", results_wanted=5)

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2

        # Job 1: Replaced with LinkedIn apply link via direct scraper!
        job1 = df.iloc[0]
        assert job1["job_url"] == "https://www.linkedin.com/jobs/view/99887766"
        assert job1["site"] == "linkedin"
        assert job1["apply_url"] == "https://www.linkedin.com/jobs/view/99887766"
        mock_scrape_from_url.assert_called_with("https://www.linkedin.com/jobs/view/99887766")

        # Job 2: Not one of our scraped sites -> retains Tanqeeb job_url
        job2 = df.iloc[1]
        assert "tanqeeb.com" in job2["job_url"]
        assert job2["site"] == "tanqeeb"
        assert job2["apply_url"] == "https://www.naukrigulf.com/data-analyst-jobs-1234"

    @patch("scrapers.tanqeeb_scraper.is_job_seen")
    @patch("scrapers.tanqeeb_scraper.fetch_tanqeeb_job_details")
    @patch("scrapers.tanqeeb_scraper.fetch_tanqeeb_full_description")
    @patch("scrapers.tanqeeb_scraper.fetch_with_retries")
    def test_skips_job_if_replaced_apply_link_already_seen(
        self, mock_fetch_page, mock_fetch_desc, mock_fetch_details, mock_is_seen
    ):
        # If the LinkedIn apply link is already in the database, is_job_seen returns True
        mock_is_seen.side_effect = lambda url: "linkedin.com" in url

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = self.SAMPLE_HTML.encode("utf-8")
        mock_fetch_page.side_effect = [mock_resp, None]

        mock_fetch_details.side_effect = lambda url: {
            "description": "Desc",
            "company": "Comp",
            "apply_url": "https://www.linkedin.com/jobs/view/99887766" if "100" in url else "https://www.naukrigulf.com/123",
            "site_name": "LinkedIn" if "100" in url else "Naukri Gulf"
        }
        mock_fetch_desc.side_effect = lambda u: "Desc"

        df = scrape_tanqeeb("python", "egypt", results_wanted=5)

        # Job 1 (LinkedIn) was already seen and skipped, only Job 2 (Naukri) is returned
        assert len(df) == 1
        assert df.iloc[0]["site"] == "tanqeeb"


class TestLinkScraperTanqeebReplacement:
    @patch("scrapers.link_scraper.scrape_job_from_url")
    @patch("scrapers.tanqeeb_scraper.fetch_tanqeeb_job_details")
    def test_link_scraper_replaces_tanqeeb_with_apply_link(self, mock_details, mock_scrape_url):
        mock_details.return_value = {
            "description": "Python Backend Engineer duties and responsibilities.",
            "company": "Top Software House",
            "apply_url": "https://www.bayt.com/en/egypt/jobs/python-backend-98765/",
            "site_name": "Bayt"
        }
        mock_scrape_url.return_value = {
            "title": "Python Backend Engineer",
            "company": "Top Software House",
            "location": "Egypt",
            "job_type": "Full-time",
            "description": "Python Backend Engineer duties and responsibilities.",
            "date_posted": "2026-10-09",
            "site": "bayt",
            "job_url": "https://www.bayt.com/en/egypt/jobs/python-backend-98765/",
            "apply_url": "https://www.bayt.com/en/egypt/jobs/python-backend-98765/"
        }

        res = _scrape_tanqeeb("https://egypt.tanqeeb.com/jobs-in-egypt/all/jobs/021129141.html")

        mock_scrape_url.assert_called_once_with("https://www.bayt.com/en/egypt/jobs/python-backend-98765/")
        assert res["site"] == "bayt"
        assert res["job_url"] == "https://www.bayt.com/en/egypt/jobs/python-backend-98765/"
        assert res["apply_url"] == "https://www.bayt.com/en/egypt/jobs/python-backend-98765/"

    @patch("scrapers.tanqeeb_scraper.fetch_tanqeeb_job_details")
    @patch("scrapers.link_scraper._scrape_bayt")
    def test_scrape_job_from_url_end_to_end_delegation(self, mock_scrape_bayt, mock_details):
        mock_details.return_value = {
            "description": "Python Backend Engineer",
            "company": "Top Software House",
            "apply_url": "https://www.bayt.com/en/egypt/jobs/python-backend-98765/",
            "site_name": "Bayt"
        }
        mock_scrape_bayt.return_value = {
            "title": "Python Backend Engineer",
            "company": "Top Software House",
            "location": "Egypt",
            "job_type": "Full-time",
            "description": "Python Backend Engineer duties and responsibilities.",
            "date_posted": "2026-10-09",
            "site": "bayt",
            "job_url": "https://www.bayt.com/en/egypt/jobs/python-backend-98765/"
        }

        res = scrape_job_from_url("https://egypt.tanqeeb.com/jobs-in-egypt/all/jobs/021129141.html")

        assert res["site"] == "bayt"
        assert res["job_url"] == "https://www.bayt.com/en/egypt/jobs/python-backend-98765/"
        assert res["apply_url"] == "https://www.bayt.com/en/egypt/jobs/python-backend-98765/"

    @patch("scrapers.tanqeeb_scraper.fetch_tanqeeb_job_details")
    @patch("curl_cffi.requests.get")
    def test_link_scraper_retains_tanqeeb_for_non_scraped_apply_link(self, mock_get, mock_details):
        mock_details.return_value = {
            "description": "Accountant position details...",
            "company": "Finance Hub",
            "apply_url": "https://www.naukrigulf.com/accountant-job-123",
            "site_name": "Naukri Gulf"
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><h1>Accountant</h1><div>Accountant position details...</div></html>"
        mock_get.return_value = mock_resp

        res = _scrape_tanqeeb("https://egypt.tanqeeb.com/jobs/details/999.html")
        assert res["site"] == "tanqeeb"
        assert res["job_url"] == "https://egypt.tanqeeb.com/jobs/details/999.html"
        assert res["apply_url"] == "https://www.naukrigulf.com/accountant-job-123"


class TestTanqeebAndApplyUrlDeduplication:
    def test_is_job_seen_checks_both_job_url_and_apply_url(self, tmp_path):
        import sqlite3
        from core import database
        from core.database import is_job_seen, get_job_by_url, save_job

        test_db = str(tmp_path / "test_dedup.db")
        with patch.object(database, "DB_PATH", test_db):
            database.init_db()

            # Save a job where job_url is Tanqeeb and apply_url is Naukri Gulf
            save_job({
                "job_id": "tanqeeb_job_1",
                "title": "Accountant",
                "company": "Finance Co",
                "job_url": "https://egypt.tanqeeb.com/jobs/details/555.html",
                "apply_url": "https://www.naukrigulf.com/job/accountant-555",
                "site": "tanqeeb"
            })

            # Both URLs must be recognized as seen!
            assert is_job_seen("https://egypt.tanqeeb.com/jobs/details/555.html") is True
            assert is_job_seen("https://www.naukrigulf.com/job/accountant-555") is True

            # Also get_job_by_url must find it by either URL
            by_job_url = get_job_by_url("https://egypt.tanqeeb.com/jobs/details/555.html")
            assert by_job_url is not None
            assert by_job_url["job_id"] == "tanqeeb_job_1"

            by_apply_url = get_job_by_url("https://www.naukrigulf.com/job/accountant-555")
            assert by_apply_url is not None
            assert by_apply_url["job_id"] == "tanqeeb_job_1"

            # Unknown URL is not seen
            assert is_job_seen("https://unknown.com/job/999") is False

    @patch("core.database.save_dropped_jobs")
    @patch("scrapers.link_scraper.scrape_job_from_url")
    @patch("scrapers.tanqeeb_scraper.is_job_seen")
    @patch("scrapers.tanqeeb_scraper.fetch_tanqeeb_job_details")
    @patch("scrapers.tanqeeb_scraper.fetch_tanqeeb_full_description")
    @patch("scrapers.tanqeeb_scraper.fetch_with_retries")
    def test_tanqeeb_records_original_link_when_replaced(
        self, mock_fetch_page, mock_fetch_desc, mock_fetch_details, mock_is_seen, mock_scrape_url, mock_save_dropped
    ):
        mock_is_seen.return_value = False
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'<html><body><div class="card"><h2><a href="/jobs/details/777.html">Engineer</a></h2></div></body></html>'
        mock_fetch_page.side_effect = [mock_resp, None]

        mock_fetch_details.return_value = {
            "description": "Engineer job description",
            "company": "Global Corp",
            "apply_url": "https://www.linkedin.com/jobs/view/777888",
            "site_name": "LinkedIn"
        }
        mock_fetch_desc.return_value = "Engineer job description"
        mock_scrape_url.return_value = {
            "title": "Engineer",
            "company": "Global Corp",
            "location": "Cairo",
            "site": "linkedin",
            "job_url": "https://www.linkedin.com/jobs/view/777888",
            "apply_url": "https://www.linkedin.com/jobs/view/777888",
            "description": "Engineer job description",
            "job_type": "Full-time",
            "date_posted": "2026-10-09"
        }

        df = scrape_tanqeeb("engineer", "egypt", results_wanted=1)
        assert len(df) == 1
        assert df.iloc[0]["job_url"] == "https://www.linkedin.com/jobs/view/777888"

        # Verify the original Tanqeeb link was recorded via save_dropped_jobs so it won't be re-fetched next time
        mock_save_dropped.assert_called()
        saved_urls = [call.args[0][0]["job_url"] for call in mock_save_dropped.call_args_list]
        assert any("777.html" in u for u in saved_urls)
