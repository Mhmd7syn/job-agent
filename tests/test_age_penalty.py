import unittest
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import date, timedelta
from core.scorer import calculate_score, is_valid_job

class TestDatePenalty(unittest.TestCase):
    def setUp(self):
        self.base_config = {
            "ROLES": [{
                "title": "AI Engineer",
                "english_terms": ["AI Engineer", "Machine Learning"],
                "years_experience": 1
            }],
            "RESUME_KEYWORDS": ["python", "pytorch", "machine learning", "deep learning"],
            "MIN_MATCHED_SKILLS": 2,
            "TARGET_LOCATIONS": ["cairo", "egypt"],
            "TARGET_LEVELS": ["Intern / Student", "Fresh Graduate / Entry-level", "Junior"],
            "LEVEL_EXCLUDE": ["Mid-Level", "Senior / Lead", "Manager / Director"],
            "EXCLUDE_KEYWORDS": [],
            "EXCLUDED_COMPANIES": [],
            "FAVORITE_COMPANIES": [],
            "DAILY_DATE_PENALTY": 1.5,
            "MAX_DATE_PENALTY": 30
        }

    def _make_job(self, days_old=0, title="Junior AI Engineer", extra_skills=""):
        post_date = (date.today() - timedelta(days=days_old)).isoformat()
        return {
            "job_id": f"test_{days_old}",
            "title": title,
            "company": "Tech Corp",
            "location": "Cairo, Egypt",
            "date_posted": post_date,
            "description": f"We are looking for an AI Engineer with python, pytorch, and machine learning skills. {extra_skills}",
            "job_type": "Full Time",
            "is_remote": False
        }

    def test_today_job_has_zero_date_penalty(self):
        job_today = self._make_job(days_old=0)
        score_today = calculate_score(job_today, self.base_config)
        self.assertGreater(score_today, 40)

    def test_older_jobs_receive_negative_date_penalty(self):
        job_today = self._make_job(days_old=0)
        job_3d = self._make_job(days_old=3)
        job_7d = self._make_job(days_old=7)
        job_10d = self._make_job(days_old=10)
        job_14d = self._make_job(days_old=14)
        job_22d = self._make_job(days_old=22)

        score_today = calculate_score(job_today, self.base_config)
        score_3d = calculate_score(job_3d, self.base_config)
        score_7d = calculate_score(job_7d, self.base_config)
        score_10d = calculate_score(job_10d, self.base_config)
        score_14d = calculate_score(job_14d, self.base_config)
        score_22d = calculate_score(job_22d, self.base_config)

        # Monotonic decrease as job gets older
        self.assertGreater(score_today, score_3d)
        self.assertGreater(score_3d, score_7d)
        self.assertGreater(score_7d, score_10d)
        self.assertGreater(score_10d, score_14d)
        self.assertGreater(score_14d, score_22d)

        # Verify exact penalty calculation:
        # At 7 days: 7 * 1.5 = 10.5 -> int(score_today - 10.5)
        self.assertEqual(score_7d, int(score_today - 7 * 1.5))
        # At 22 days: 22 * 1.5 = 33.0, which is capped at 30:
        self.assertEqual(score_22d, int(score_today - 30))

    def test_five_day_old_higher_score_job_beats_today_job(self):
        # 5-day-old job with strong match (base score ~64 with favorite company)
        five_day_job = self._make_job(days_old=5, extra_skills="deep learning computer vision")
        five_day_job["company"] = "Favorite Tech Corp"
        config_with_fav = dict(self.base_config)
        config_with_fav["FAVORITE_COMPANIES"] = ["Favorite Tech Corp"]

        # Today job with standard match (base score ~49)
        today_job = self._make_job(days_old=0)

        score_5d = calculate_score(five_day_job, config_with_fav)
        score_today = calculate_score(today_job, config_with_fav)

        # Because penalty at 5 days is only 5 * 1.5 = 7.5 points (instead of 17.5),
        # the higher-match 5-day job cleanly beats today's job:
        self.assertGreater(score_5d, score_today, "A 5-day-old job with a higher match must outrank a today job")

    def test_new_job_beats_older_job_with_same_base(self):
        fresh_job = self._make_job(days_old=0)
        older_job = self._make_job(days_old=5)

        score_fresh = calculate_score(fresh_job, self.base_config)
        score_older = calculate_score(older_job, self.base_config)

        self.assertGreater(score_fresh, score_older, "When base scores are equal, fresher job must rank higher")

    def test_no_floor_value_allows_score_to_drop_below_zero(self):
        # A job with low base score (e.g. 15) when penalized with 30 points can drop below 0
        low_base_job = {
            "job_id": "test_low_base",
            "title": "Data Assistant",
            "company": "Tech Corp",
            "location": "Cairo, Egypt",
            "date_posted": (date.today() - timedelta(days=30)).isoformat(),
            "description": "python and machine learning",
            "job_type": "Full Time",
            "is_remote": False
        }
        base_score = calculate_score(low_base_job, self.base_config, apply_date_penalty=False)
        final_score = calculate_score(low_base_job, self.base_config, apply_date_penalty=True)
        # Verify base score is positive and penalty (30) is subtracted without an artificial floor
        self.assertEqual(final_score, base_score - 30)
        if base_score < 30:
            self.assertLess(final_score, 0)

    def test_max_penalty_cap_of_30_is_respected(self):
        # At 60 days, 60 * 1.5 = 90, but must be capped at 30
        job_today = self._make_job(days_old=0)
        job_60d = self._make_job(days_old=60)
        base = calculate_score(job_today, self.base_config)
        old_score = calculate_score(job_60d, self.base_config)
        self.assertEqual(base - old_score, 30)

    def test_apply_date_penalty_flag_returns_unpenalized_base_score(self):
        old_job = self._make_job(days_old=25)
        base_score = calculate_score(old_job, self.base_config, apply_date_penalty=False)
        penalized_score = calculate_score(old_job, self.base_config, apply_date_penalty=True)
        self.assertEqual(base_score - penalized_score, 30)
        # is_valid_job should be True because the job matches career criteria despite age penalty
        self.assertTrue(is_valid_job(old_job, config=self.base_config))

    def test_unrelated_job_remains_zero(self):
        unrelated = {
            "job_id": "unrelated",
            "title": "Accountant",
            "company": "Finance Inc",
            "location": "Cairo",
            "date_posted": date.today().isoformat(),
            "description": "General accounting role with excel and ledgers."
        }
        score = calculate_score(unrelated, self.base_config)
        self.assertEqual(score, 0)
        self.assertFalse(is_valid_job(unrelated, config=self.base_config))

    def test_future_date_clamped_to_zero(self):
        future_date = (date.today() + timedelta(days=1)).isoformat()
        job_future = self._make_job(days_old=0)
        job_future["date_posted"] = future_date

        score_future = calculate_score(job_future, self.base_config)
        score_today = calculate_score(self._make_job(days_old=0), self.base_config)
        self.assertEqual(score_future, score_today)

    def test_degree_years_does_not_penalize(self):
        # "Bachelor degree (4 years)" should not trigger an experience penalty
        cfg = dict(self.base_config)
        cfg["ROLES"] = [{"title": "AI Engineer", "english_terms": ["AI Engineer"], "years_experience": 0}]
        job_normal = self._make_job(days_old=0, extra_skills="")
        job_degree = self._make_job(days_old=0, extra_skills="Requirements: Bachelor degree in Computer Science (4 years).")
        score_normal = calculate_score(job_normal, cfg)
        score_degree = calculate_score(job_degree, cfg)
        self.assertEqual(score_normal, score_degree)

    def test_fresh_grad_zero_to_two_years_zero_penalty(self):
        # "0-2 years of experience" must be recognized as min 0 years, giving 0 penalty for user_exp=0
        cfg = dict(self.base_config)
        cfg["ROLES"] = [{"title": "AI Engineer", "english_terms": ["AI Engineer"], "years_experience": 0}]
        job_normal = self._make_job(days_old=0, extra_skills="")
        job_range = self._make_job(days_old=0, extra_skills="Requirements: 0-2 years of relevant experience.")
        score_normal = calculate_score(job_normal, cfg)
        score_range = calculate_score(job_range, cfg)
        self.assertEqual(score_normal, score_range)

    def test_experience_penalty_five_per_year(self):
        # 2 years required experience when candidate has 0 years should dock 2 * 5 = 10 points
        cfg = dict(self.base_config)
        cfg["ROLES"] = [{"title": "AI Engineer", "english_terms": ["AI Engineer"], "years_experience": 0}]
        job_normal = self._make_job(days_old=0, extra_skills="")
        job_2y = self._make_job(days_old=0, extra_skills="Requirements: 2 years of experience.")
        score_normal = calculate_score(job_normal, cfg)
        score_2y = calculate_score(job_2y, cfg)
        self.assertEqual(score_normal - score_2y, 10)

    def test_range_experience_with_to_zero_penalty(self):
        # "0 to 2 years of experience" should register min 0 years
        cfg = dict(self.base_config)
        cfg["ROLES"] = [{"title": "AI Engineer", "english_terms": ["AI Engineer"], "years_experience": 0}]
        job_normal = self._make_job(days_old=0, extra_skills="")
        job_range = self._make_job(days_old=0, extra_skills="Requirements: 0 to 2 years of experience.")
        score_normal = calculate_score(job_normal, cfg)
        score_range = calculate_score(job_range, cfg)
        self.assertEqual(score_normal, score_range)

    def test_seniority_in_title_penalizes_fifty(self):
        cfg = dict(self.base_config)
        cfg["EXCLUDE_KEYWORDS"] = ["senior", "lead", "manager"]
        job_senior_title = self._make_job(days_old=0, title="Senior AI Engineer", extra_skills="")
        job_junior_title = self._make_job(days_old=0, title="Junior AI Engineer", extra_skills="")
        score_senior = calculate_score(job_senior_title, cfg)
        score_junior = calculate_score(job_junior_title, cfg)
        self.assertEqual(score_senior, 0)
        self.assertGreater(score_junior, 40)

    def test_seniority_in_desc_does_not_penalize(self):
        cfg = dict(self.base_config)
        cfg["EXCLUDE_KEYWORDS"] = ["senior", "lead", "manager", "head"]
        job_clean = self._make_job(days_old=0, title="Junior AI Engineer", extra_skills="")
        job_with_hierarchy = self._make_job(
            days_old=0,
            title="Junior AI Engineer",
            extra_skills="You will report to the Data Science Manager, work with the team lead, and collaborate with senior engineers."
        )
        score_clean = calculate_score(job_clean, cfg)
        score_hierarchy = calculate_score(job_with_hierarchy, cfg)
        # Seniority keywords in description should NOT dock points
        self.assertEqual(score_clean, score_hierarchy)

    def test_domain_exclude_in_desc_penalizes(self):
        cfg = dict(self.base_config)
        cfg["EXCLUDE_KEYWORDS"] = ["sales", "cold calling"]
        job_clean = self._make_job(days_old=0, title="Junior AI Engineer", extra_skills="")
        job_with_sales = self._make_job(
            days_old=0,
            title="Junior AI Engineer",
            extra_skills="This role also includes direct business sales responsibilities."
        )
        score_clean = calculate_score(job_clean, cfg)
        score_sales = calculate_score(job_with_sales, cfg)
        # Non-seniority domain exclude in description docks 15 points
        self.assertEqual(score_clean - score_sales, 15)

    def test_company_age_five_or_ten_years_ignored(self):
        cfg = dict(self.base_config)
        cfg["ROLES"] = [{"title": "AI Engineer", "english_terms": ["AI Engineer"], "years_experience": 0}]
        job_clean = self._make_job(days_old=0, extra_skills="")
        job_company_10y = self._make_job(days_old=0, extra_skills="We are an innovative tech company with 10 years experience in the market.")
        job_company_5y = self._make_job(days_old=0, extra_skills="Our team has 5 years of experience delivering top-tier solutions.")
        score_clean = calculate_score(job_clean, cfg)
        score_10y = calculate_score(job_company_10y, cfg)
        score_5y = calculate_score(job_company_5y, cfg)
        self.assertEqual(score_clean, score_10y)
        self.assertEqual(score_clean, score_5y)

    def test_company_mention_with_candidate_requirement_penalizes(self):
        cfg = dict(self.base_config)
        cfg["ROLES"] = [{"title": "AI Engineer", "english_terms": ["AI Engineer"], "years_experience": 0}]
        job_clean = self._make_job(days_old=0, extra_skills="")
        job_req = self._make_job(days_old=0, extra_skills="We are seeking an AI Engineer with 3+ years experience.")
        score_clean = calculate_score(job_clean, cfg)
        score_req = calculate_score(job_req, cfg)
        self.assertEqual(score_clean - score_req, 15)

    def test_competition_and_hackathon_recognized_as_scholarship(self):
        cfg = dict(self.base_config)
        job_comp = {
            "job_id": "test_comp",
            "title": "AI Innovation Competition 2026",
            "company": "Tech Foundation",
            "location": "Cairo, Egypt",
            "date_posted": date.today().isoformat(),
            "description": "Annual student competition for deep learning.",
            "job_type": "competition"
        }
        score = calculate_score(job_comp, cfg)
        self.assertGreater(score, 0)

    def test_bachelor_duration_stripped_with_real_experience(self):
        cfg = dict(self.base_config)
        cfg["ROLES"] = [{"title": "AI Engineer", "english_terms": ["AI Engineer"], "years_experience": 0}]
        job_clean = self._make_job(days_old=0, extra_skills="")
        job_both = self._make_job(days_old=0, extra_skills="Requirements: Bachelor degree in CS (4 years) with 2 years experience.")
        score_clean = calculate_score(job_clean, cfg)
        score_both = calculate_score(job_both, cfg)
        self.assertEqual(score_clean - score_both, 10)

if __name__ == "__main__":
    unittest.main()
