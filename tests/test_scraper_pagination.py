import pytest
import os
import sys
from unittest.mock import patch, MagicMock
import pandas as pd

from scrapers.wuzzuf_scraper import scrape_wuzzuf
from scrapers.bayt_scraper import scrape_bayt
from scrapers.glassdoor_scraper import scrape_glassdoor, build_glassdoor_url


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
