import os
import sys
import unittest
from unittest.mock import patch, MagicMock

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from scrapers.glassdoor_scraper import (
    build_glassdoor_url,
    fetch_glassdoor_full_description,
    scrape_glassdoor
)


class TestGlassdoorScraper(unittest.TestCase):
    def test_build_glassdoor_url_location_no_locid(self):
        # Standard location search
        url_egypt = build_glassdoor_url("python developer", "Egypt")
        self.assertIn("sc.keyword=python+developer", url_egypt)
        self.assertIn("locKeyword=Egypt", url_egypt)
        self.assertNotIn("locId=", url_egypt)
        self.assertNotIn("locT=", url_egypt)

        # City search
        url_cairo = build_glassdoor_url("machine learning", "Cairo")
        self.assertIn("locKeyword=Cairo", url_cairo)
        self.assertNotIn("locId=", url_cairo)

    def test_build_glassdoor_url_remote(self):
        # Remote location
        url_remote = build_glassdoor_url("data engineer", "Remote")
        self.assertIn("locKeyword=Remote", url_remote)
        self.assertIn("remoteWorkType=1", url_remote)
        self.assertNotIn("locId=", url_remote)

        # Worldwide location
        url_worldwide = build_glassdoor_url("ai researcher", "Worldwide")
        self.assertIn("locKeyword=Remote", url_worldwide)
        self.assertIn("remoteWorkType=1", url_worldwide)

    def test_build_glassdoor_url_from_age(self):
        url_age = build_glassdoor_url("devops", "Egypt", hours_old=72)
        self.assertIn("fromAge=3", url_age)

    def test_fetch_full_description_invalid_url(self):
        self.assertEqual(fetch_glassdoor_full_description(""), "")
        self.assertEqual(fetch_glassdoor_full_description("https://www.glassdoor.com/Job/jobs.htm?sc.keyword=python"), "")

    @patch("curl_cffi.requests.get")
    def test_fetch_full_description_html_container(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"""
        <html>
            <body>
                <div class="JobDetails_jobDescription">
                    We are looking for a Senior AI Engineer with Python, PyTorch, and deep learning expertise.
                    Minimum 5 years of industry experience required.
                </div>
            </body>
        </html>
        """
        mock_get.return_value = mock_resp

        desc = fetch_glassdoor_full_description("https://www.glassdoor.com/job-listing/senior-ai-engineer-12345")
        self.assertIn("Python, PyTorch", desc)
        self.assertIn("5 years", desc)

    @patch("curl_cffi.requests.get")
    def test_fetch_full_description_json_ld(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"""
        <html>
            <head>
                <script type="application/ld+json">
                {
                    "@context": "http://schema.org",
                    "@type": "JobPosting",
                    "title": "Data Analyst",
                    "description": "<p>We are seeking a Data Analyst skilled in SQL and Tableau.</p><p>Must have strong communication.</p>"
                }
                </script>
            </head>
            <body></body>
        </html>
        """
        mock_get.return_value = mock_resp

        desc = fetch_glassdoor_full_description("https://www.glassdoor.com/partner/jobListing.htm?id=99999")
        self.assertIn("SQL and Tableau", desc)

    @patch("scrapers.glassdoor_scraper.is_job_seen", return_value=False)
    @patch("scrapers.glassdoor_scraper.fetch_glassdoor_full_description")
    def test_scrape_glassdoor_calls_fetch_full_description(self, mock_fetch_desc, mock_is_seen):
        mock_fetch_desc.return_value = "Complete full job description with Python, SQL, and Docker requirements."

        mock_driver = MagicMock()
        mock_driver.get_page_source.return_value = """
        <html>
            <body>
                <ul>
                    <li>
                        <a href="/job-listing/test-role-123" class="JobTitle">AI Engineer</a>
                        <span class="EmployerName">Tech Innovations</span>
                        <div class="location">Cairo, Egypt</div>
                        <p>Snippet card text</p>
                    </li>
                </ul>
            </body>
        </html>
        """

        df = scrape_glassdoor("ai engineer", "Cairo", results_wanted=5, driver=mock_driver)
        self.assertEqual(len(df), 1)

        mock_fetch_desc.assert_called_once_with("https://www.glassdoor.com/job-listing/test-role-123", driver=mock_driver)
        job = df.iloc[0].to_dict()
        self.assertEqual(job["title"], "AI Engineer")
        self.assertEqual(job["company"], "Tech Innovations")
        self.assertEqual(job["description"], "Complete full job description with Python, SQL, and Docker requirements.")
        self.assertEqual(job["job_id"], "ai engineer|tech innovations")
        self.assertEqual(job["site"], "glassdoor")


if __name__ == "__main__":
    unittest.main()
