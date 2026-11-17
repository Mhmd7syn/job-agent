import pytest
import os
import sys
from unittest.mock import patch, MagicMock
import pandas as pd

from scrapers.wuzzuf_scraper import scrape_wuzzuf
from scrapers.bayt_scraper import scrape_bayt
from scrapers.glassdoor_scraper import scrape_glassdoor, build_glassdoor_url
from scrapers.tanqeeb_scraper import scrape_tanqeeb
from scrapers.playwright_scraper import scrape_linkedin_guest_api


WUZZUF_PAGE_1 = """
<html><body>
  <div class="css-pkv5jc">
    <h2><a href="/jobs/p/1-wz">Backend Python</a></h2>
    <a class="css-ipsyv7">Company A</a>
    <span class="css-16x61xq">Cairo</span>
    <span class="eoyjyou0">Full Time</span>
    <p>Card 1 text</p>
  </div>
</body></html>
"""

WUZZUF_PAGE_2 = """
<html><body>
  <div class="css-pkv5jc">
    <h2><a href="/jobs/p/2-wz">Frontend React</a></h2>
    <a class="css-ipsyv7">Company B</a>
    <span class="css-16x61xq">Giza</span>
    <span class="eoyjyou0">Full Time</span>
    <p>Card 2 text</p>
  </div>
</body></html>
"""

BAYT_PAGE_1 = """
<html><body><ul>
  <li class="has-pointer-d">
    <h2><a href="/en/egypt/jobs/dev-1/">Dev 1</a></h2>
    <b class="p10r">Bayt Co 1</b>
    <span class="t-mute">Cairo</span>
    <div class="t-small">Desc 1</div>
  </li>
</ul></body></html>
"""

BAYT_PAGE_2 = """
<html><body><ul>
  <li class="has-pointer-d">
    <h2><a href="/en/egypt/jobs/dev-2/">Dev 2</a></h2>
    <b class="p10r">Bayt Co 2</b>
    <span class="t-mute">Alexandria</span>
    <div class="t-small">Desc 2</div>
  </li>
</ul></body></html>
"""

GLASSDOOR_PAGE_1 = """
<html><body><ul>
  <li>
    <a href="/job-listing/gd-123">
      <span class="JobTitle">GD Dev 1</span>
    </a>
    <span class="EmployerName">GD Corp 1</span>
    <span class="location">Cairo</span>
  </li>
</ul></body></html>
"""

GLASSDOOR_PAGE_2 = """
<html><body><ul>
  <li>
    <a href="/job-listing/gd-456">
      <span class="JobTitle">GD Dev 2</span>
    </a>
    <span class="EmployerName">GD Corp 2</span>
    <span class="location">Giza</span>
  </li>
</ul></body></html>
"""

TANQEEB_PAGE_1 = """
<html><body>
  <div class="card">
    <h2><a href="/jobs/11-tq">Seen Tanqeeb Dev</a></h2>
    <span class="company">Tanqeeb Co 1</span>
    <span class="location">Cairo</span>
    <span class="date">today</span>
  </div>
</body></html>
"""

TANQEEB_PAGE_2 = """
<html><body>
  <div class="card">
    <h2><a href="/jobs/22-tq">Fresh Tanqeeb Dev</a></h2>
    <span class="company">Tanqeeb Co 2</span>
    <span class="location">Alexandria</span>
    <span class="date">today</span>
  </div>
</body></html>
"""

LINKEDIN_PAGE_1 = """
<html><body>
  <li>
    <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/1000000001?refId=123"></a>
    <h3 class="base-search-card__title">Seen LinkedIn Dev</h3>
    <h4 class="base-search-card__subtitle">LI Corp 1</h4>
    <span class="job-search-card__location">Cairo</span>
    <time datetime="2026-11-17">Today</time>
  </li>
</body></html>
"""

LINKEDIN_PAGE_2 = """
<html><body>
  <li>
    <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/2000000002?refId=456"></a>
    <h3 class="base-search-card__title">Fresh LinkedIn Dev</h3>
    <h4 class="base-search-card__subtitle">LI Corp 2</h4>
    <span class="job-search-card__location">Giza</span>
    <time datetime="2026-11-17">Today</time>
  </li>
</body></html>
"""


class TestScraperPagination:
    @patch("scrapers.wuzzuf_scraper.is_job_seen", return_value=False)
    @patch("scrapers.wuzzuf_scraper.fetch_wuzzuf_full_description", return_value="Full details")
    def test_wuzzuf_paginates_until_results_wanted(self, mock_desc, mock_seen):
        mock_driver = MagicMock()
        opened_urls = []

        def side_effect_open(url, *args):
            opened_urls.append(url)
            if "start=0" in url:
                mock_driver.get_page_source.return_value = WUZZUF_PAGE_1
            elif "start=1" in url:
                mock_driver.get_page_source.return_value = WUZZUF_PAGE_2
            else:
                mock_driver.get_page_source.return_value = "<html><body></body></html>"

        mock_driver.uc_open_with_reconnect.side_effect = side_effect_open
        mock_driver.get_page_source.return_value = WUZZUF_PAGE_1

        # Request 2 jobs when each page has 1
        df = scrape_wuzzuf("developer", "Cairo", results_wanted=2, driver=mock_driver)

        assert len(df) == 2
        assert any("start=0" in u for u in opened_urls)
        assert any("start=1" in u for u in opened_urls)
        assert df.iloc[0]["title"] == "Backend Python"
        assert df.iloc[1]["title"] == "Frontend React"

    @patch("scrapers.bayt_scraper.is_job_seen", return_value=False)
    @patch("scrapers.bayt_scraper.fetch_bayt_full_description", return_value="Full details")
    @patch("scrapers.bayt_scraper._fetch_bayt_page")
    def test_bayt_paginates_until_results_wanted(self, mock_fetch_page, mock_desc, mock_seen):
        requested_urls = []

        def side_effect_fetch(url, driver=None):
            requested_urls.append(url)
            if "page=1" in url:
                return BAYT_PAGE_1
            elif "page=2" in url:
                return BAYT_PAGE_2
            return ""

        mock_fetch_page.side_effect = side_effect_fetch

        # Request 2 jobs
        df = scrape_bayt("engineer", "egypt", results_wanted=2)

        assert len(df) == 2
        assert any("page=1" in u for u in requested_urls)
        assert any("page=2" in u for u in requested_urls)
        assert df.iloc[0]["title"] == "Dev 1"
        assert df.iloc[1]["title"] == "Dev 2"

    def test_build_glassdoor_url_pagination(self):
        url_p1 = build_glassdoor_url("python", "Cairo", page=1)
        assert "p=" not in url_p1

        url_p2 = build_glassdoor_url("python", "Cairo", page=2)
        assert "p=2" in url_p2

        url_p3 = build_glassdoor_url("python", "Cairo", page=3)
        assert "p=3" in url_p3

    @patch("scrapers.glassdoor_scraper.is_job_seen", return_value=False)
    @patch("scrapers.glassdoor_scraper.fetch_glassdoor_full_description", return_value="Full GD details")
    def test_glassdoor_paginates_until_results_wanted(self, mock_desc, mock_seen):
        mock_driver = MagicMock()
        opened_urls = []

        def side_effect_open(url, *args):
            opened_urls.append(url)
            if "p=2" in url:
                mock_driver.get_page_source.return_value = GLASSDOOR_PAGE_2
            else:
                mock_driver.get_page_source.return_value = GLASSDOOR_PAGE_1

        mock_driver.uc_open_with_reconnect.side_effect = side_effect_open
        mock_driver.get_page_source.return_value = GLASSDOOR_PAGE_1

        df = scrape_glassdoor("analyst", "Cairo", results_wanted=2, driver=mock_driver)

        assert len(df) == 2
        assert any("p=2" in u for u in opened_urls)
        assert df.iloc[0]["title"] == "GD Dev 1"
        assert df.iloc[1]["title"] == "GD Dev 2"

    @patch("scrapers.wuzzuf_scraper.fetch_wuzzuf_full_description", return_value="Full details")
    def test_wuzzuf_paginates_when_page_1_has_only_seen_jobs(self, mock_desc):
        mock_driver = MagicMock()
        opened_urls = []

        def side_effect_open(url, *args):
            opened_urls.append(url)
            if "start=0" in url:
                mock_driver.get_page_source.return_value = WUZZUF_PAGE_1
            elif "start=1" in url:
                mock_driver.get_page_source.return_value = WUZZUF_PAGE_2
            else:
                mock_driver.get_page_source.return_value = "<html><body></body></html>"

        mock_driver.uc_open_with_reconnect.side_effect = side_effect_open
        mock_driver.get_page_source.return_value = WUZZUF_PAGE_1

        # Page 1 job (1-wz) is seen, Page 2 job (2-wz) is unseen
        with patch("scrapers.wuzzuf_scraper.is_job_seen", side_effect=lambda u: "1-wz" in u):
            df = scrape_wuzzuf("developer", "Cairo", results_wanted=1, driver=mock_driver)

        assert len(df) == 1
        assert any("start=0" in u for u in opened_urls)
        assert any("start=1" in u for u in opened_urls)
        assert df.iloc[0]["title"] == "Frontend React"

    @patch("scrapers.bayt_scraper.fetch_bayt_full_description", return_value="Full details")
    @patch("scrapers.bayt_scraper._fetch_bayt_page")
    def test_bayt_paginates_when_page_1_has_only_seen_jobs(self, mock_fetch_page, mock_desc):
        requested_urls = []

        def side_effect_fetch(url, driver=None):
            requested_urls.append(url)
            if "page=1" in url:
                return BAYT_PAGE_1
            elif "page=2" in url:
                return BAYT_PAGE_2
            return ""

        mock_fetch_page.side_effect = side_effect_fetch

        # Page 1 job (dev-1) is seen, Page 2 job (dev-2) is unseen
        with patch("scrapers.bayt_scraper.is_job_seen", side_effect=lambda u: "dev-1" in u):
            df = scrape_bayt("engineer", "egypt", results_wanted=1)

        assert len(df) == 1
        assert any("page=1" in u for u in requested_urls)
        assert any("page=2" in u for u in requested_urls)
        assert df.iloc[0]["title"] == "Dev 2"

    @patch("scrapers.glassdoor_scraper.fetch_glassdoor_full_description", return_value="Full GD details")
    def test_glassdoor_paginates_when_page_1_has_only_seen_jobs(self, mock_desc):
        mock_driver = MagicMock()
        opened_urls = []

        def side_effect_open(url, *args):
            opened_urls.append(url)
            if "p=2" in url:
                mock_driver.get_page_source.return_value = GLASSDOOR_PAGE_2
            else:
                mock_driver.get_page_source.return_value = GLASSDOOR_PAGE_1

        mock_driver.uc_open_with_reconnect.side_effect = side_effect_open
        mock_driver.get_page_source.return_value = GLASSDOOR_PAGE_1

        # Page 1 job (gd-123) is seen, Page 2 job (gd-456) is unseen
        with patch("scrapers.glassdoor_scraper.is_job_seen", side_effect=lambda u: "gd-123" in u):
            df = scrape_glassdoor("analyst", "Cairo", results_wanted=1, driver=mock_driver)

        assert len(df) == 1
        assert any("p=2" in u for u in opened_urls)
        assert df.iloc[0]["title"] == "GD Dev 2"

    @patch("scrapers.tanqeeb_scraper.fetch_tanqeeb_job_details", return_value={})
    @patch("scrapers.tanqeeb_scraper.fetch_with_retries")
    def test_tanqeeb_paginates_when_page_1_seen_and_orders_by_recent(self, mock_fetch, mock_details):
        requested_urls = []

        def side_effect_fetch(url):
            requested_urls.append(url)
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            if "page_no=1" in url:
                mock_resp.content = TANQEEB_PAGE_1.encode("utf-8")
                return mock_resp
            elif "page_no=2" in url:
                mock_resp.content = TANQEEB_PAGE_2.encode("utf-8")
                return mock_resp
            return None

        mock_fetch.side_effect = side_effect_fetch

        # Page 1 job (11-tq) is seen, Page 2 job (22-tq) is unseen
        with patch("scrapers.tanqeeb_scraper.is_job_seen", side_effect=lambda u: "11-tq" in u):
            df = scrape_tanqeeb("developer", "Cairo", results_wanted=1)

        assert len(df) == 1
        assert any("order_by=recent" in u for u in requested_urls)
        assert any("page_no=1" in u for u in requested_urls)
        assert any("page_no=2" in u for u in requested_urls)
        assert df.iloc[0]["title"] == "Fresh Tanqeeb Dev"

    @patch("curl_cffi.requests.get")
    def test_linkedin_guest_api_paginates_and_sorts_by_date(self, mock_get):
        requested_urls = []

        def side_effect_get(url, *args, **kwargs):
            requested_urls.append(url)
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            if "start=0" in url:
                mock_resp.text = LINKEDIN_PAGE_1
            elif "start=25" in url:
                mock_resp.text = LINKEDIN_PAGE_2
            else:
                mock_resp.text = ""
            return mock_resp

        mock_get.side_effect = side_effect_get

        # Page 1 job (1000000001) is seen, Page 2 job (2000000002) is unseen
        with patch("scrapers.playwright_scraper.is_job_seen", side_effect=lambda u: "1000000001" in u):
            df = scrape_linkedin_guest_api("python", "Cairo", results_wanted=1)

        assert len(df) == 1
        assert any("sortBy=DD" in u for u in requested_urls)
        assert any("start=0" in u for u in requested_urls)
        assert any("start=25" in u for u in requested_urls)
        assert df.iloc[0]["title"] == "Fresh LinkedIn Dev"
