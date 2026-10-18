import unittest
import os
import sys
import sqlite3
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.database import (
    DB_PATH,
    save_or_update_job,
    get_autopilot_applied_tracker,
    is_job_eligible_for_autopilot,
    register_autopilot_applied,
    get_autopilot_candidate_jobs,
)


class TestAutoPilotEligibility(unittest.TestCase):
    def setUp(self):
        self.valid_job = {
            "job_id": "test_ai_eng_1",
            "title": "Junior AI Engineer",
            "company": "Tech Innovations",
            "location": "Cairo, Egypt",
            "job_url": "https://example.com/jobs/ai-1",
            "apply_url": "https://example.com/apply/ai-1",
            "relevance_score": 85.0,
            "status": "pending",
            "is_applied": 0,
            "apply_status": "unapplied",
            "apply_type": "email",
            "description": "We are seeking a Junior AI Engineer with Python, PyTorch, and Machine Learning skills.",
            "apply_payload": json.dumps({"recipient_email": "jobs@techinnovations.com"})
        }

    def test_eligible_job_passes(self):
        eligible, reason = is_job_eligible_for_autopilot(self.valid_job, min_score=70)
        self.assertTrue(eligible)
        self.assertEqual(reason, "Eligible")

    def test_not_related_status_rejected(self):
        job = dict(self.valid_job, status="not_related")
        eligible, reason = is_job_eligible_for_autopilot(job, min_score=70)
        self.assertFalse(eligible)
        self.assertIn("not related", reason.lower())

    def test_filtered_status_rejected(self):
        job = dict(self.valid_job, status="filtered")
        eligible, reason = is_job_eligible_for_autopilot(job, min_score=70)
        self.assertFalse(eligible)
        self.assertIn("filtered", reason.lower())

    def test_applied_status_rejected(self):
        job = dict(self.valid_job, status="applied")
        eligible, reason = is_job_eligible_for_autopilot(job, min_score=70)
        self.assertFalse(eligible)
        self.assertIn("already marked as applied", reason.lower())

    def test_arbitrary_status_rejected(self):
        job = dict(self.valid_job, status="archived")
        eligible, reason = is_job_eligible_for_autopilot(job, min_score=70)
        self.assertFalse(eligible)
        self.assertIn("must be pending or liked", reason.lower())

    def test_liked_status_is_eligible(self):
        job = dict(self.valid_job, status="liked")
        eligible, reason = is_job_eligible_for_autopilot(job, min_score=70)
        self.assertTrue(eligible)

    def test_is_applied_flag_rejected(self):
        job = dict(self.valid_job, is_applied=1)
        eligible, reason = is_job_eligible_for_autopilot(job, min_score=70)
        self.assertFalse(eligible)
        self.assertIn("is_applied=1", reason.lower())

    def test_apply_status_flag_rejected(self):
        job = dict(self.valid_job, apply_status="applied")
        eligible, reason = is_job_eligible_for_autopilot(job, min_score=70)
        self.assertFalse(eligible)
        self.assertIn("apply_status='applied'", reason.lower())

    def test_score_zero_or_negative_rejected(self):
        job_zero = dict(self.valid_job, relevance_score=0)
        eligible, reason = is_job_eligible_for_autopilot(job_zero, min_score=70)
        self.assertFalse(eligible)
        self.assertIn("<= 0", reason)

        job_neg = dict(self.valid_job, relevance_score=-15)
        eligible_neg, reason_neg = is_job_eligible_for_autopilot(job_neg, min_score=0)
        self.assertFalse(eligible_neg)
        self.assertIn("<= 0", reason_neg)

    def test_score_below_minimum_rejected(self):
        job = dict(self.valid_job, relevance_score=65)
        eligible, reason = is_job_eligible_for_autopilot(job, min_score=70)
        self.assertFalse(eligible)
        self.assertIn("below minimum threshold", reason.lower())

    def test_unrelated_career_fails_criteria_validation(self):
        job_unrelated = {
            "job_id": "accountant_job_1",
            "title": "Senior Accountant",
            "company": "Finance Hub",
            "relevance_score": 85.0,  # artificially high score
            "status": "pending",
            "is_applied": 0,
            "description": "Handling company balance sheets and tax filings."
        }
        eligible, reason = is_job_eligible_for_autopilot(job_unrelated, min_score=70)
        self.assertFalse(eligible)
        self.assertIn("fails career criteria", reason.lower())

    def test_tracker_cross_dedup_applied_urls(self):
        tracker = {
            "applied_job_ids": set(),
            "applied_urls": {"https://example.com/jobs/ai-1"},
            "applied_title_company": set(),
            "applied_emails": set(),
            "applied_phones": set(),
            "not_related_job_ids": set(),
            "not_related_urls": set(),
            "not_related_title_company": set()
        }
        eligible, reason = is_job_eligible_for_autopilot(self.valid_job, applied_tracker=tracker, min_score=70)
        self.assertFalse(eligible)
        self.assertIn("url was already applied to", reason.lower())

    def test_tracker_cross_dedup_applied_title_company(self):
        tracker = {
            "applied_job_ids": set(),
            "applied_urls": set(),
            "applied_title_company": {("junior ai engineer", "tech innovations")},
            "applied_emails": set(),
            "applied_phones": set(),
            "not_related_job_ids": set(),
            "not_related_urls": set(),
            "not_related_title_company": set()
        }
        # Another job listing with different ID and URL but same title and company
        diff_listing = dict(self.valid_job, job_id="different_id_2", job_url="https://different.com/job")
        eligible, reason = is_job_eligible_for_autopilot(diff_listing, applied_tracker=tracker, min_score=70)
        self.assertFalse(eligible)
        self.assertIn("already applied for", reason.lower())

    def test_tracker_cross_dedup_not_related(self):
        tracker = {
            "applied_job_ids": set(),
            "applied_urls": set(),
            "applied_title_company": set(),
            "applied_emails": set(),
            "applied_phones": set(),
            "not_related_job_ids": set(),
            "not_related_urls": set(),
            "not_related_title_company": {("junior ai engineer", "tech innovations")}
        }
        eligible, reason = is_job_eligible_for_autopilot(self.valid_job, applied_tracker=tracker, min_score=70)
        self.assertFalse(eligible)
        self.assertIn("marked as not related", reason.lower())

    def test_email_recipient_dedup(self):
        tracker = {
            "applied_job_ids": set(),
            "applied_urls": set(),
            "applied_title_company": set(),
            "applied_emails": {"jobs@techinnovations.com"},
            "applied_phones": set(),
            "not_related_job_ids": set(),
            "not_related_urls": set(),
            "not_related_title_company": set()
        }
        diff_job = dict(self.valid_job, job_id="ai_eng_other", company="Other Corp", title="Data Analyst")
        eligible, reason = is_job_eligible_for_autopilot(diff_job, applied_tracker=tracker, min_score=70, channel="email")
        self.assertFalse(eligible)
        self.assertIn("already sent application to recruiter email", reason.lower())

    def test_whatsapp_phone_dedup(self):
        tracker = {
            "applied_job_ids": set(),
            "applied_urls": set(),
            "applied_title_company": set(),
            "applied_emails": set(),
            "applied_phones": {"201012345678"},
            "not_related_job_ids": set(),
            "not_related_urls": set(),
            "not_related_title_company": set()
        }
        wa_job = dict(
            self.valid_job,
            apply_type="whatsapp",
            apply_payload=json.dumps({"phone": "+20 10 1234 5678"})
        )
        eligible, reason = is_job_eligible_for_autopilot(wa_job, applied_tracker=tracker, min_score=70, channel="whatsapp")
        self.assertFalse(eligible)
        self.assertIn("already sent whatsapp message to phone", reason.lower())

    def test_in_batch_tracker_registration(self):
        tracker = {
            "applied_job_ids": set(),
            "applied_urls": set(),
            "applied_title_company": set(),
            "applied_emails": set(),
            "applied_phones": set(),
            "not_related_job_ids": set(),
            "not_related_urls": set(),
            "not_related_title_company": set()
        }
        # First job is eligible
        eligible1, _ = is_job_eligible_for_autopilot(self.valid_job, applied_tracker=tracker, min_score=70)
        self.assertTrue(eligible1)

        # Register first job as applied
        register_autopilot_applied(self.valid_job, tracker, recipient_email="jobs@techinnovations.com")

        # Second job with same role or URL is immediately blocked
        duplicate_job = dict(self.valid_job, job_id="duplicate_batch_job", job_url="https://different.com/job")
        eligible2, reason2 = is_job_eligible_for_autopilot(duplicate_job, applied_tracker=tracker, min_score=70)
        self.assertFalse(eligible2)
        self.assertIn("already applied", reason2.lower())

    def test_save_or_update_job_preserves_not_related_and_applied(self):
        """Verifies that re-scraping does not overwrite not_related status or applied flag."""
        import tempfile
        import core.database as db

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            temp_db = f.name

        orig_db = db.DB_PATH
        try:
            db.DB_PATH = temp_db
            db.init_db()

            # Insert a job marked not_related
            job1 = {
                "job_id": "test_not_rel_job",
                "title": "Data Analyst",
                "company": "Company A",
                "status": "not_related",
                "is_applied": 0,
                "relevance_score": 80
            }
            db.save_or_update_job(job1, force_pending=False)

            # Re-scrape the same job with force_pending=True (default scraper behavior)
            re_scraped_job = {
                "job_id": "test_not_rel_job",
                "title": "Data Analyst",
                "company": "Company A",
                "relevance_score": 82
            }
            updated, _ = db.save_or_update_job(re_scraped_job, force_pending=True)
            self.assertEqual(updated["status"], "not_related", "Status 'not_related' must be preserved despite force_pending=True")

            # Insert an applied job
            job2 = {
                "job_id": "test_applied_job",
                "title": "AI Engineer",
                "company": "Company B",
                "status": "liked",
                "is_applied": 1,
                "relevance_score": 90
            }
            db.save_or_update_job(job2, force_pending=False)

            # Re-scrape the same job with is_applied=0
            re_scraped_applied = {
                "job_id": "test_applied_job",
                "title": "AI Engineer",
                "company": "Company B",
                "is_applied": 0
            }
            updated_applied, _ = db.save_or_update_job(re_scraped_applied, force_pending=False)
            self.assertEqual(updated_applied["is_applied"], 1, "is_applied=1 must be preserved on re-scrape")
        finally:
            db.DB_PATH = orig_db
            if os.path.exists(temp_db):
                os.remove(temp_db)

    def test_channel_disabled_in_settings_blocks_job(self):
        """Verifies that is_job_eligible_for_autopilot rejects jobs for unchecked channels in settings."""
        channels_settings = {
            "email": False,
            "whatsapp": True,
            "easy_apply": False,
            "platform": False
        }
        # Email job should be rejected when email is False
        email_job = dict(self.valid_job, apply_type="email")
        eligible_email, reason_email = is_job_eligible_for_autopilot(
            email_job,
            channels_enabled=channels_settings
        )
        self.assertFalse(eligible_email)
        self.assertIn("disabled in settings", reason_email.lower())

        # WhatsApp job should be accepted when whatsapp is True
        wa_job = dict(self.valid_job, apply_type="whatsapp", apply_payload=json.dumps({"phone": "+201011112222"}))
        eligible_wa, _ = is_job_eligible_for_autopilot(
            wa_job,
            channels_enabled=channels_settings
        )
        self.assertTrue(eligible_wa)

        # Easy apply and platform should be rejected
        ea_job = dict(self.valid_job, apply_type="easy_apply")
        eligible_ea, reason_ea = is_job_eligible_for_autopilot(
            ea_job,
            channels_enabled=channels_settings
        )
        self.assertFalse(eligible_ea)
        self.assertIn("disabled in settings", reason_ea.lower())

        # Unsupported auto-apply types (e.g. manual, job_board) must always be rejected
        manual_job = dict(self.valid_job, apply_type="manual")
        eligible_m, reason_m = is_job_eligible_for_autopilot(
            manual_job,
            channels_enabled=channels_settings
        )
        self.assertFalse(eligible_m)
        self.assertIn("not supported for auto-apply", reason_m.lower())

    def test_get_autopilot_candidate_jobs_filters_by_channels_enabled(self):
        """Verifies get_autopilot_candidate_jobs only retrieves apply_types enabled in settings."""
        from core.database import get_autopilot_candidate_jobs
        channels_settings = {
            "email": False,
            "whatsapp": False,
            "easy_apply": False,
            "platform": False
        }
        res = get_autopilot_candidate_jobs(
            apply_types=["email", "whatsapp", "easy_apply", "platform"],
            channels_enabled=channels_settings
        )
        self.assertEqual(res, [], "Must return empty list when all channels are disabled")

    def test_master_autopilot_skips_disabled_channels_even_when_forced(self):
        """Verifies run_master_autopilot_cycle skips any channel disabled in settings even when force=True."""
        from unittest.mock import patch
        from appliers.master_orchestrator import run_master_autopilot_cycle

        mock_profile = {
            "auto_apply_settings": {
                "enabled": True,
                "channels_enabled": {
                    "email": False,
                    "whatsapp": False,
                    "easy_apply": False,
                    "platform": False
                }
            }
        }
        with patch("appliers.master_orchestrator.load_profile", return_value=mock_profile), \
             patch("appliers.master_orchestrator.run_email_autopilot_batch") as mock_email, \
             patch("appliers.master_orchestrator.run_whatsapp_autopilot_batch") as mock_wa, \
             patch("appliers.master_orchestrator._process_autonomous_form_jobs") as mock_form:

            res = run_master_autopilot_cycle(force=True, dry_run=True)
            self.assertEqual(res["status"], "success")
            self.assertEqual(res["results"]["email_batch"]["status"], "skipped")
            self.assertEqual(res["results"]["whatsapp_batch"]["status"], "skipped")
            self.assertEqual(res["results"]["easy_apply_batch"]["status"], "skipped")

            mock_email.assert_not_called()
            mock_wa.assert_not_called()
            mock_form.assert_not_called()

    def test_autonomous_form_jobs_skips_when_channels_disabled(self):
        """Verifies _process_autonomous_form_jobs returns skipped when form channels are not enabled."""
        from unittest.mock import patch
        from appliers.master_orchestrator import _process_autonomous_form_jobs

        mock_profile = {
            "auto_apply_settings": {
                "channels_enabled": {
                    "easy_apply": False,
                    "platform": False
                }
            }
        }
        with patch("appliers.master_orchestrator.load_profile", return_value=mock_profile):
            res = _process_autonomous_form_jobs(min_score=70)
            self.assertEqual(res["status"], "skipped")
            self.assertEqual(res["processed_count"], 0)


if __name__ == "__main__":
    unittest.main()
