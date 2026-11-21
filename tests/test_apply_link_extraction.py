import unittest
from unittest.mock import patch, MagicMock
from scrapers.common import (
    resolve_canonical_apply_url,
    extract_embedded_apply_url,
    is_valid_specific_apply_url,
)


class TestApplyLinkExtraction(unittest.TestCase):
    def test_extract_query_param_redirects(self):
        # LinkedIn safety redirect
        raw_li = "https://www.linkedin.com/safety/go/?url=https%3A%2F%2Fjobs.lever.co%2Fstripe%2F12345"
        resolved = resolve_canonical_apply_url(raw_li)
        self.assertEqual(resolved, "https://jobs.lever.co/stripe/12345")

        # Generic target/redirect param
        raw_redir = "https://tracker.example.com/redirect?target=https%3A%2F%2Fboards.greenhouse.io%2Fjob%2F999"
        resolved_redir = resolve_canonical_apply_url(raw_redir)
        self.assertEqual(resolved_redir, "https://boards.greenhouse.io/job/999")

    @patch("curl_cffi.requests.get")
    def test_unshorten_shortlink_http_redirect(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 302
        mock_resp.headers = {"Location": "https://company.wd3.myworkdayjobs.com/careers/job/123"}
        mock_resp.url = "https://company.wd3.myworkdayjobs.com/careers/job/123"
        mock_get.return_value = mock_resp

        short_url = "https://lnkd.in/gAbCdEf"
        resolved = resolve_canonical_apply_url(short_url)
        self.assertEqual(resolved, "https://company.wd3.myworkdayjobs.com/careers/job/123")

    @patch("curl_cffi.requests.get")
    def test_circular_redirect_protection(self, mock_get):
        resp_a = MagicMock()
        resp_a.status_code = 302
        resp_a.headers = {"Location": "https://example.com/b"}
        resp_a.url = "https://example.com/b"

        resp_b = MagicMock()
        resp_b.status_code = 302
        resp_b.headers = {"Location": "https://example.com/a"}
        resp_b.url = "https://example.com/a"

        mock_get.side_effect = [resp_a, resp_b, resp_a, resp_b]

        # Must not loop infinitely
        res = resolve_canonical_apply_url("https://example.com/a", max_hops=3)
        self.assertTrue(res in ["https://example.com/a", "https://example.com/b"])

    def test_extract_embedded_apply_url_ats_text(self):
        desc = (
            "We are hiring a Senior Python Engineer!\n"
            "Responsibilities: Build APIs, manage DB.\n"
            "Apply directly via our ATS portal: https://boards.greenhouse.io/acme/jobs/456789\n"
            "Equal opportunity employer."
        )
        url = extract_embedded_apply_url(text_content=desc)
        self.assertEqual(url, "https://boards.greenhouse.io/acme/jobs/456789")

    def test_extract_embedded_apply_url_workday(self):
        desc = (
            "Join Valeo Cairo AI team.\n"
            "Please submit your application here: "
            "https://valeo.wd3.myworkdayjobs.com/en-US/valeo_jobs/job/Cairo/AI-Engineer_REQ123?mode=apply"
        )
        url = extract_embedded_apply_url(text_content=desc)
        self.assertEqual(
            url,
            "https://valeo.wd3.myworkdayjobs.com/en-US/valeo_jobs/job/Cairo/AI-Engineer_REQ123?mode=apply"
        )

    def test_extract_embedded_apply_url_forms(self):
        desc = "To apply, please fill out the Google Form: https://forms.gle/xyz9876543210"
        url = extract_embedded_apply_url(text_content=desc)
        self.assertEqual(url, "https://forms.gle/xyz9876543210")

    def test_extract_embedded_apply_url_from_html(self):
        html = """
        <div class="job-description">
            <p>Great opportunity for Data Analysts.</p>
            <p><a class="btn-apply" href="https://jobs.lever.co/fintech/789012">Click here to apply on Lever</a></p>
        </div>
        """
        url = extract_embedded_apply_url(html_content=html)
        self.assertEqual(url, "https://jobs.lever.co/fintech/789012")

    def test_extract_embedded_apply_url_from_html_data_attribute(self):
        html = """
        <div class="job-header">
            <button class="apply-btn" data-apply-url="https://company.ashbyhq.com/startup/job-999">Apply Now</button>
        </div>
        """
        url = extract_embedded_apply_url(html_content=html)
        self.assertEqual(url, "https://company.ashbyhq.com/startup/job-999")

    def test_filters_out_aggregators_and_social(self):
        desc = (
            "Check our LinkedIn page: https://www.linkedin.com/company/techcorp\n"
            "Share on Facebook: https://www.facebook.com/sharer/sharer.php?u=xyz\n"
            "Also listed on Wuzzuf: https://wuzzuf.net/jobs/p/12345-python-dev\n"
            "Also listed on Tanqeeb: https://egypt.tanqeeb.com/jobs/details/999\n"
            "Also listed on Bayt: https://www.bayt.com/en/egypt/jobs/dev-123/\n"
        )
        url = extract_embedded_apply_url(text_content=desc)
        # None of these should be considered a direct destination ATS apply URL
        self.assertIsNone(url)

    def test_is_valid_specific_apply_url(self):
        # Valid specific URLs
        self.assertTrue(is_valid_specific_apply_url("https://boards.greenhouse.io/stripe/jobs/123"))
        self.assertTrue(is_valid_specific_apply_url("https://company.wd3.myworkdayjobs.com/careers/job/123"))
        self.assertTrue(is_valid_specific_apply_url("https://forms.gle/123456"))
        self.assertTrue(is_valid_specific_apply_url("https://company.com/careers/apply?id=999"))

        # Invalid or generic URLs (should NOT be used for deduplication)
        self.assertFalse(is_valid_specific_apply_url(""))
        self.assertFalse(is_valid_specific_apply_url(None))
        self.assertFalse(is_valid_specific_apply_url("https://google.com"))
        self.assertFalse(is_valid_specific_apply_url("https://wuzzuf.net/"))
        self.assertFalse(is_valid_specific_apply_url("https://www.linkedin.com/"))
        self.assertFalse(is_valid_specific_apply_url("https://egypt.tanqeeb.com/"))
        self.assertFalse(is_valid_specific_apply_url("https://www.bayt.com/"))
        self.assertFalse(is_valid_specific_apply_url("https://company.com/"))

    @patch("scrapers.link_scraper.extract_feed_posts_with_ai")
    def test_linkedin_post_embedded_apply_url(self, mock_ai):
        from scrapers.link_scraper import _scrape_linkedin_post
        mock_ai.return_value = {
            "jobs": [{
                "title": "Staff AI Engineer",
                "company": "DeepMind Partner",
                "location": "Cairo, Egypt",
                "description": "We are seeking a Staff AI Engineer. Apply directly at: https://boards.greenhouse.io/deepmind/jobs/778899",
                "job_type": "Full-time"
            }]
        }
        raw_text = (
            "We are seeking a Staff AI Engineer. "
            "Apply directly at: https://boards.greenhouse.io/deepmind/jobs/778899"
        )
        job = _scrape_linkedin_post("https://www.linkedin.com/posts/activity-12345", raw_text=raw_text)
        self.assertEqual(job["apply_url"], "https://boards.greenhouse.io/deepmind/jobs/778899")

    @patch("core.database.is_job_seen")
    @patch("core.database.get_job_by_url")
    @patch("scrapers.link_scraper._scrape_generic")
    def test_scrape_job_from_url_deduplicates_on_apply_url(self, mock_generic, mock_get_job, mock_is_seen):
        from scrapers.link_scraper import scrape_job_from_url

        # The URL itself is new, but its destination apply_url is already known in the database
        mock_is_seen.side_effect = lambda u: u == "https://valeo.wd3.myworkdayjobs.com/careers/job/999"
        mock_get_job.return_value = {
            "job_id": "valeo_cairo_ai",
            "title": "AI Engineer",
            "company": "Valeo",
            "job_url": "https://valeo.wd3.myworkdayjobs.com/careers/job/999",
            "apply_url": "https://valeo.wd3.myworkdayjobs.com/careers/job/999",
            "site": "workday",
            "relevance_score": 92.0
        }
        mock_generic.return_value = {
            "title": "AI Engineer",
            "company": "Valeo",
            "location": "Cairo",
            "job_url": "https://aggregator.example.com/job/555",
            "apply_url": "https://valeo.wd3.myworkdayjobs.com/careers/job/999",
            "description": "Join Valeo AI team.",
            "site": "web"
        }

        res = scrape_job_from_url("https://aggregator.example.com/job/555", scraper_type="generic")
        self.assertEqual(res["job_id"], "valeo_cairo_ai")
        self.assertEqual(res["title"], "AI Engineer")

    def test_classify_and_extract_routes_to_platform_with_extracted_apply_url(self):
        from core.apply_classifier import classify_and_extract
        job = {
            "title": "Software Engineer",
            "company": "Acme Corp",
            "site": "wuzzuf",
            "job_url": "https://wuzzuf.net/jobs/p/123-acme-software-engineer",
            "apply_url": "https://acme.greenhouse.io/jobs/456",
            "description": "Apply on our portal."
        }
        res = classify_and_extract(job)
        self.assertEqual(res["apply_type"], "platform")
        self.assertEqual(res["apply_payload"]["platform"], "greenhouse")
        self.assertEqual(res["apply_payload"]["portal_url"], "https://acme.greenhouse.io/jobs/456")


if __name__ == "__main__":
    unittest.main()
