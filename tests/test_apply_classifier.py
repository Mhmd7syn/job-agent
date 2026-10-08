import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from core.apply_classifier import classify_and_extract


class TestApplyClassifier(unittest.TestCase):
    def test_glassdoor_apply_on_employer_site_without_ats(self):
        job = {
            "title": "Data Scientist",
            "company": "Banque Misr",
            "site": "glassdoor",
            "job_url": "https://www.glassdoor.com/job-listing/data-scientist-banque-misr-JV_IC3438985.htm?jl=1009971443375",
            "apply_url": "https://www.glassdoor.com/job-listing/data-scientist-banque-misr-JV_IC3438985.htm?jl=1009971443375",
            "description": "Banque Misr is hiring a Data Scientist in Cairo. Please see details below.",
            "is_easy_apply": False
        }
        res = classify_and_extract(job)
        self.assertEqual(res["apply_type"], "manual")
        self.assertEqual(res["apply_payload"]["source"], "employer_site")
        self.assertEqual(res["apply_payload"]["portal_url"], job["apply_url"])

    def test_glassdoor_apply_on_employer_site_with_ats_in_apply_url(self):
        valeo_workday = "https://valeo.wd3.myworkdayjobs.com/en-US/valeo_jobs/job/Cairo/AI-Engineer--LIGHT_REQ2026072297?mode=job"
        job = {
            "title": "AI Engineer, LIGHT",
            "company": "Valeo",
            "site": "glassdoor",
            "job_url": "https://www.glassdoor.com/job-listing/ai-engineer-light-valeo-JV_IC3438985.htm?jl=1010069907051",
            "apply_url": valeo_workday,
            "description": "Valeo is a tech global company designing breakthrough solutions.",
            "is_easy_apply": False
        }
        res = classify_and_extract(job)
        self.assertEqual(res["apply_type"], "platform")
        self.assertEqual(res["apply_payload"]["platform"], "workday")
        self.assertEqual(res["apply_payload"]["portal_url"], valeo_workday)

    def test_glassdoor_easy_apply(self):
        job = {
            "title": "Machine Learning Engineer",
            "company": "Tech Corp",
            "site": "glassdoor",
            "job_url": "https://www.glassdoor.com/job-listing/ml-engineer-12345",
            "apply_url": "https://www.glassdoor.com/partner/jobListing.htm?jobListingId=12345&ea=1",
            "description": "Join our fast-growing startup.",
            "is_easy_apply": True
        }
        res = classify_and_extract(job)
        self.assertEqual(res["apply_type"], "easy_apply")
        self.assertEqual(res["apply_payload"]["platform"], "glassdoor_easy_apply")

    def test_glassdoor_easy_apply_sqlite_integer_one(self):
        job = {
            "title": "AI Engineer",
            "company": "Bayan-Tech",
            "site": "glassdoor",
            "job_url": "https://www.glassdoor.com/job-listing/ai-engineer-bayan-tech-JV_IC3440853_KO0,11_KE12,22.htm?jl=1010264061842",
            "apply_url": "https://www.glassdoor.com/partner/jobListing.htm?pos=101",
            "description": "Design and develop AI-powered solutions.",
            "is_easy_apply": 1  # Stored as integer 1 in SQLite
        }
        res = classify_and_extract(job)
        self.assertEqual(res["apply_type"], "easy_apply")
        self.assertEqual(res["apply_payload"]["platform"], "glassdoor_easy_apply")

    def test_glassdoor_unverified_flag_is_job_board(self):
        job = {
            "title": "Software Engineer",
            "company": "Microsoft",
            "site": "glassdoor",
            "job_url": "https://www.glassdoor.com/job-listing/software-engineer-12345",
            "description": "Internship opportunity at Microsoft.",
            "is_easy_apply": None
        }
        res = classify_and_extract(job)
        self.assertEqual(res["apply_type"], "job_board")
        self.assertEqual(res["apply_payload"]["board_name"], "Glassdoor")

    def test_ats_detection_greenhouse_and_lever(self):
        gh_job = {
            "title": "Backend Engineer",
            "company": "Stripe",
            "site": "linkedin",
            "job_url": "https://boards.greenhouse.io/stripe/jobs/123456",
            "description": "Apply for Stripe backend team."
        }
        res_gh = classify_and_extract(gh_job)
        self.assertEqual(res_gh["apply_type"], "platform")
        self.assertEqual(res_gh["apply_payload"]["platform"], "greenhouse")

        lever_job = {
            "title": "Data Engineer",
            "company": "Figma",
            "site": "manual",
            "job_url": "https://jobs.lever.co/figma/abcdef",
            "description": "Apply for Figma."
        }
        res_lever = classify_and_extract(lever_job)
        self.assertEqual(res_lever["apply_type"], "platform")
        self.assertEqual(res_lever["apply_payload"]["platform"], "lever")

    def test_native_job_board_wuzzuf(self):
        wuzzuf_job = {
            "title": "Data Analyst",
            "company": "Cairo Tech",
            "site": "wuzzuf",
            "job_url": "https://wuzzuf.net/jobs/p/12345-Data-Analyst",
            "description": "Apply through Wuzzuf."
        }
        res = classify_and_extract(wuzzuf_job)
        self.assertEqual(res["apply_type"], "job_board")
        self.assertEqual(res["apply_payload"]["board_name"], "Wuzzuf")

    def test_extract_subject_hint_and_no_false_positive_line(self):
        from core.apply_classifier import extract_subject_hint
        text1 = 'Please mention "Data Analyst" in the email subject line.'
        self.assertEqual(extract_subject_hint(text1), "Data Analyst")

        text2 = 'Send CV with subject line: "Junior AI Engineer"'
        self.assertEqual(extract_subject_hint(text2), "Junior AI Engineer")

        text3 = 'Mention Python Developer in the subject line.'
        self.assertNotEqual(extract_subject_hint(text3), "line")

    def test_linkedin_post_with_email_classified_as_email(self):
        job = {
            "title": "Data Analyst (Fresh Graduates)",
            "job_url": "https://www.linkedin.com/posts/mohamed-elkadey-ab9164188_hiring-dataanalyst-freshgraduates-share-7487446934845247488-GQj_/",
            "site": "linkedin_posts",
            "description": """
                🚀 We're Hiring | Data Analyst (Fresh Graduates)
                Send your CV to: smrityhr417@gmail.com
                Please mention "Data Analyst" in the email subject line.
            """
        }
        res = classify_and_extract(job)
        self.assertEqual(res["apply_type"], "email")
        self.assertEqual(res["apply_payload"]["recipient_email"], "smrityhr417@gmail.com")
        self.assertEqual(res["apply_payload"]["subject_hint"], "Data Analyst")

    def test_normalize_site_linkedin_and_whatsapp_export(self):
        from core.job_utils import normalize_site
        # WhatsApp export with LinkedIn post URL should normalize to linkedin_posts
        self.assertEqual(normalize_site("whatsapp_export", "https://www.linkedin.com/posts/test-job-123"), "linkedin_posts")
        # lnkd shortlink should normalize to linkedin_posts
        self.assertEqual(normalize_site("lnkd", "https://lnkd.in/p/eY2KVq-U"), "linkedin_posts")
        # Standard LinkedIn job view URL
        self.assertEqual(normalize_site("linkedin", "https://www.linkedin.com/jobs/view/4453115810/"), "linkedin")
        # WhatsApp export without known URL
        self.assertEqual(normalize_site("whatsapp_export", "https://unknownsite.com/job/1"), "web")

    def test_direct_employer_link_from_linkedin_apply_button(self):
        job = {
            "title": "Applied Scientist II",
            "company": "Microsoft",
            "site": "linkedin",
            "job_url": "https://eg.linkedin.com/jobs/view/applied-scientist-ii-at-microsoft-4462809773",
            "apply_url": "https://apply.careers.microsoft.com/careers/job/1970393556984145?utm_source=linkedin&domain=microsoft.com&src=LinkedIn",
            "description": "Microsoft is hiring..."
        }
        res = classify_and_extract(job)
        self.assertEqual(res["apply_type"], "manual")
        self.assertEqual(res["apply_payload"]["portal_url"], "https://apply.careers.microsoft.com/careers/job/1970393556984145?utm_source=linkedin&domain=microsoft.com&src=LinkedIn")
        self.assertEqual(res["apply_payload"]["source"], "employer_site")
        self.assertTrue(res["apply_payload"]["is_direct_employer_link"])

    def test_direct_employer_link_with_utm_query_does_not_falsely_trigger_aggregator(self):
        job = {
            "title": "Supply Chain Analyst",
            "company": "Amazon",
            "site": "linkedin",
            "job_url": "https://eg.linkedin.com/jobs/view/supply-chain-analyst-at-amazon-4456345896",
            "apply_url": "https://www.amazon.jobs/jobs/10481069?cmpid=SPLICX0248M&utm_source=linkedin.com&ss=paid",
            "description": "Amazon is hiring..."
        }
        res = classify_and_extract(job)
        self.assertEqual(res["apply_payload"]["portal_url"], "https://www.amazon.jobs/jobs/10481069?cmpid=SPLICX0248M&utm_source=linkedin.com&ss=paid")
        self.assertTrue(res["apply_payload"]["is_direct_employer_link"])

    def test_direct_employer_link_extracted_from_description(self):
        job = {
            "title": "Data Scientist I - QuantumBlack, AI by McKinsey",
            "company": "McKinsey & Company",
            "site": "glassdoor",
            "job_url": "https://www.glassdoor.com/job-listing/data-scientist-i-quantumblack-ai-by-mckinsey-mckinsey-company-JV_IC3438985_KO0,44_KE45,61.htm?jl=1010260474128",
            "apply_url": "",
            "description": "At McKinsey, you'll work on make-or-break problems. Ready to apply? Search our open roles https://www.mckinsey.com/careers/search-jobs"
        }
        res = classify_and_extract(job)
        self.assertEqual(res["apply_payload"]["portal_url"], "https://www.mckinsey.com/careers/search-jobs")
        self.assertEqual(res["apply_payload"]["source"], "employer_site")
        self.assertTrue(res["apply_payload"]["is_direct_employer_link"])

    def test_aggregator_partner_redirect_marked_as_not_direct_employer(self):
        job = {
            "title": "AI Engineer",
            "company": "Nile Bits",
            "site": "glassdoor",
            "job_url": "https://www.glassdoor.com/job-listing/ai-engineer.htm",
            "apply_url": "https://www.glassdoor.com/partner/jobListing.htm?pos=101&jobListingId=123",
            "description": "Join Nile Bits..."
        }
        res = classify_and_extract(job)
        self.assertEqual(res["apply_payload"]["source"], "employer_site")
        self.assertFalse(res["apply_payload"]["is_direct_employer_link"])


if __name__ == "__main__":
    unittest.main()
