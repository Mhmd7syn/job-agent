import pytest
import datetime
from unittest.mock import patch, MagicMock
import pandas as pd

from scrapers.wuzzuf_scraper import scrape_wuzzuf, fetch_wuzzuf_full_description
from scrapers.bayt_scraper import scrape_bayt, fetch_bayt_full_description
from scrapers.tanqeeb_scraper import scrape_tanqeeb, fetch_tanqeeb_full_description


# Sample HTML snippets for testing
WUZZUF_HTML = """
<html>
<body>
  <div class="css-pkv5jc">
    <h2><a href="/jobs/p/123-python-dev">Senior Python Engineer</a></h2>
    <a class="css-ipsyv7">Tech Corp</a>
    <span class="css-16x61xq">Cairo, Egypt</span>
    <span class="eoyjyou0">Full Time</span>
    <span class="eoyjyou0">Senior</span>
    <div class="css-1k5ee52"><div>2 days ago</div></div>
    <p>Short card snippet description of python dev</p>
  </div>
  <div class="css-pkv5jc">
    <h2><a href="/jobs/p/456-data-analyst">Junior Data Analyst</a></h2>
    <a class="css-ipsyv7">Analytics Inc</a>
    <span class="css-16x61xq">Giza, Egypt</span>
    <span class="eoyjyou0">Part Time</span>
    <span class="eoyjyou0">Junior</span>
    <div class="css-1k5ee52"><div>1 hour ago</div></div>
    <p>Short snippet for data analyst</p>
  </div>
</body>
</html>
"""

BAYT_HTML = """
<html>
<body>
  <ul>
    <li class="has-pointer-d">
      <h2><a href="/en/egypt/jobs/backend-engineer-999/">Backend Engineer</a></h2>
      <b class="p10r">Bayt Soft</b>
      <span class="t-mute">Cairo, Egypt</span>
      <div class="t-small">Short card snippet for backend engineer</div>
      <div class="t-mute">1 day ago</div>
    </li>
    <li class="has-pointer-d">
      <h2><a href="/en/egypt/jobs/frontend-engineer-888/">Frontend Engineer</a></h2>
      <b class="p10r">Web Labs</b>
      <span class="t-mute">Alexandria, Egypt</span>
      <div class="t-small">Short card snippet for frontend engineer</div>
      <div class="t-mute">2 days ago</div>
    </li>
  </ul>
</body>
</html>
"""

TANQEEB_HTML = """
<html>
<body>
  <div class="card">
    <h2><a href="/jobs/details/111-ai-engineer">AI Engineer</a></h2>
    <span class="company">AI Tech</span>
    <span class="location">Cairo</span>
    <span class="date">1 day ago</span>
    <p>Card snippet for AI Engineer</p>
  </div>
  <div class="card">
    <h2><a href="/jobs/details/222-ml-engineer">ML Engineer</a></h2>
    <span class="company">Data Dynamics</span>
    <span class="location">Giza</span>
    <span class="date">today</span>
    <p>Card snippet for ML Engineer</p>
  </div>
</body>
</html>
"""


class TestWuzzufConcurrent:
    @patch("scrapers.wuzzuf_scraper.is_job_seen")
    @patch("scrapers.wuzzuf_scraper.fetch_wuzzuf_full_description")
    def test_wuzzuf_concurrent_success_and_fallback(self, mock_fetch_desc, mock_is_seen):
        mock_is_seen.return_value = False

        # 1st job returns rich full description, 2nd job returns empty (fallback to card)
        def side_effect_desc(url):
            if "123" in url:
                return "This is an extensive full job description for Senior Python Engineer with all qualifications and requirements listed in full."
            return ""

        mock_fetch_desc.side_effect = side_effect_desc

        mock_driver = MagicMock()
        mock_driver.get_page_source.return_value = WUZZUF_HTML

        df = scrape_wuzzuf("python", "Cairo, Egypt", results_wanted=5, driver=mock_driver)

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2
        assert mock_fetch_desc.call_count == 2

        job1 = df.iloc[0]
        assert "extensive full job description" in job1["description"]
        assert job1["title"] == "Senior Python Engineer"
        assert job1["company"] == "Tech Corp"
        assert job1["job_id"] is not None  # Normalized schema

        job2 = df.iloc[1]
        assert "Short snippet for data analyst" in job2["description"]  # Fallback
        assert job2["title"] == "Junior Data Analyst"

    @patch("scrapers.wuzzuf_scraper.is_job_seen")
    @patch("scrapers.wuzzuf_scraper.fetch_wuzzuf_full_description")
    def test_wuzzuf_skips_seen_jobs_before_fetch(self, mock_fetch_desc, mock_is_seen):
        # 1st job is seen, 2nd is new
        mock_is_seen.side_effect = lambda url: "123" in url

        mock_driver = MagicMock()
        mock_driver.get_page_source.return_value = WUZZUF_HTML

        df = scrape_wuzzuf("python", "Cairo, Egypt", results_wanted=5, driver=mock_driver)

        assert len(df) == 1
        assert df.iloc[0]["title"] == "Junior Data Analyst"
        # mock_fetch_desc should only have been called ONCE for the unseen job
        assert mock_fetch_desc.call_count == 1


class TestBaytConcurrent:
    @patch("scrapers.bayt_scraper.is_job_seen")
    @patch("scrapers.bayt_scraper.fetch_bayt_full_description")
    def test_bayt_concurrent_success_and_fallback(self, mock_fetch_desc, mock_is_seen):
        mock_is_seen.return_value = False

        def side_effect_desc(url):
            if "backend" in url:
                return "Full backend engineer duties and responsibilities with detailed technical stack requirements."
            return ""

        mock_fetch_desc.side_effect = side_effect_desc

        # Mock curl_cffi fast HTTP response
        with patch("curl_cffi.requests.get") as mock_http_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = "has-pointer-d " + BAYT_HTML + " " * 10000
            mock_http_get.return_value = mock_resp

            df = scrape_bayt("backend", "egypt", results_wanted=5)

            assert isinstance(df, pd.DataFrame)
            assert len(df) == 2
            assert mock_fetch_desc.call_count == 2

            job1 = df.iloc[0]
            assert "Full backend engineer duties" in job1["description"]
            assert job1["site"] == "bayt"
            assert job1["job_id"] is not None

            job2 = df.iloc[1]
            assert job2["description"] == "Short card snippet for frontend engineer"

    @patch("scrapers.bayt_scraper.is_job_seen")
    @patch("scrapers.bayt_scraper.fetch_bayt_full_description")
    def test_bayt_skips_seen_jobs(self, mock_fetch_desc, mock_is_seen):
        mock_is_seen.side_effect = lambda url: "backend" in url

        with patch("curl_cffi.requests.get") as mock_http_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = "has-pointer-d " + BAYT_HTML + " " * 10000
            mock_http_get.return_value = mock_resp

            df = scrape_bayt("backend", "egypt", results_wanted=5)

            assert len(df) == 1
            assert df.iloc[0]["title"] == "Frontend Engineer"
            assert mock_fetch_desc.call_count == 1


class TestTanqeebConcurrent:
    @patch("scrapers.tanqeeb_scraper.is_job_seen")
    @patch("scrapers.tanqeeb_scraper.fetch_tanqeeb_full_description")
    @patch("scrapers.tanqeeb_scraper.fetch_with_retries")
    def test_tanqeeb_concurrent_success_and_fallback(self, mock_fetch_page, mock_fetch_desc, mock_is_seen):
        mock_is_seen.return_value = False

        # Mock page fetch: return HTML on page 1, None on page 2
        mock_page_resp = MagicMock()
        mock_page_resp.status_code = 200
        mock_page_resp.content = TANQEEB_HTML.encode("utf-8")
        mock_fetch_page.side_effect = [mock_page_resp, None]

        def side_effect_desc(url):
            if "111" in url:
                return "Complete job description for AI Engineer with PhD/Master requirements and experience."
            return ""

        mock_fetch_desc.side_effect = side_effect_desc

        df = scrape_tanqeeb("ai engineer", "egypt", results_wanted=5)

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2
        assert mock_fetch_desc.call_count == 2

        job1 = df.iloc[0]
        assert "Complete job description for AI Engineer" in job1["description"]
        assert job1["site"] == "tanqeeb"
        assert job1["job_id"] is not None

        job2 = df.iloc[1]
        assert "Card snippet for ML Engineer" in job2["description"]

    @patch("scrapers.tanqeeb_scraper.is_job_seen")
    @patch("scrapers.tanqeeb_scraper.fetch_tanqeeb_full_description")
    @patch("scrapers.tanqeeb_scraper.fetch_with_retries")
    def test_tanqeeb_skips_seen_jobs(self, mock_fetch_page, mock_fetch_desc, mock_is_seen):
        mock_is_seen.side_effect = lambda url: "111" in url

        mock_page_resp = MagicMock()
        mock_page_resp.status_code = 200
        mock_page_resp.content = TANQEEB_HTML.encode("utf-8")
        mock_fetch_page.side_effect = [mock_page_resp, None]

        df = scrape_tanqeeb("ai engineer", "egypt", results_wanted=5)

        assert len(df) == 1
        assert df.iloc[0]["title"] == "ML Engineer"
        assert mock_fetch_desc.call_count == 1
