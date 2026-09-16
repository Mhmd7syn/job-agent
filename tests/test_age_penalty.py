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
                "arabic_terms": [],
                "years_experience": 1
            }],
            "RESUME_KEYWORDS": ["python", "pytorch", "machine learning", "deep learning"],
            "MIN_MATCHED_SKILLS": 2,
            "TARGET_LOCATIONS": ["cairo", "egypt"],
            "TARGET_LEVELS": ["junior", "intern"],
            "EXCLUDE_KEYWORDS": ["senior"],
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

if __name__ == "__main__":
    unittest.main()
