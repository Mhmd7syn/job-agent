import pytest
import os
import sys
from unittest.mock import patch, MagicMock, call
import pandas as pd

import job_agent


class TestPhasedScraperExecution:
    @patch("job_agent.process_scraped_batch")
    @patch("job_agent.write_progress")
    @patch("job_agent.ScanCheckpoint")
    @patch("job_agent.cleanup_old_jobs")
    @patch("job_agent.rescore_all_jobs", create=True)
    def test_http_only_mode_never_opens_browsers(
        self, mock_rescore, mock_cleanup, mock_checkpoint_cls, mock_write_progress, mock_batch
    ):
        mock_checkpoint = MagicMock()
        mock_checkpoint.is_completed.return_value = False
        mock_checkpoint_cls.return_value = mock_checkpoint

        # Set SITES to HTTP-only
        with patch.object(job_agent, "SITES", ["tanqeeb", "bayt"]), \
             patch.object(job_agent, "SEARCH_TERMS", ["Python"]), \
             patch.object(job_agent, "LOCATION", ["Egypt"]), \
             patch("job_agent.scrape_tanqeeb") as mock_tanqeeb, \
             patch("job_agent.scrape_bayt") as mock_bayt, \
             patch("scrapers.selenium_scraper.SeleniumSession") as mock_sb_session, \
             patch("job_agent.LinkedInSession") as mock_li_session:

            mock_tanqeeb.return_value = pd.DataFrame([{"title": "Dev 1", "job_url": "http://1"}])
            mock_bayt.return_value = pd.DataFrame([{"title": "Dev 2", "job_url": "http://2"}])

            job_agent.main()

            # Verify HTTP scrapers were called
            assert mock_tanqeeb.called
            assert mock_bayt.called

            # Verify neither browser session was ever instantiated or entered
            assert not mock_sb_session.called
            assert not mock_li_session.called

            # Checkpoint key should have http: prefix
            mock_checkpoint.mark_completed.assert_called_with("http:Python|Egypt")

    @patch("job_agent.process_scraped_batch")
    @patch("job_agent.write_progress")
    @patch("job_agent.ScanCheckpoint")
    @patch("job_agent.cleanup_old_jobs")
    @patch("job_agent.rescore_all_jobs", create=True)
    def test_phases_are_strictly_isolated_and_never_overlap(
        self, mock_rescore, mock_cleanup, mock_checkpoint_cls, mock_write_progress, mock_batch
    ):
        mock_checkpoint = MagicMock()
        mock_checkpoint.is_completed.return_value = False
        mock_checkpoint_cls.return_value = mock_checkpoint

        active_browsers = []
        events_timeline = []

        class MockLinkedInCtx:
            def __enter__(self):
                active_browsers.append("playwright")
                events_timeline.append(("enter_playwright", list(active_browsers)))
                # Assert Selenium is NOT active when Playwright is entered
                assert "selenium" not in active_browsers, "Dual browser collision! Selenium is open during Playwright!"
                return MagicMock()

            def __exit__(self, *args):
                active_browsers.remove("playwright")
                events_timeline.append(("exit_playwright", list(active_browsers)))

        class MockSeleniumCtx:
            def __enter__(self):
                active_browsers.append("selenium")
                events_timeline.append(("enter_selenium", list(active_browsers)))
                # Assert Playwright is NOT active when Selenium is entered
                assert "playwright" not in active_browsers, "Dual browser collision! Playwright is open during Selenium!"
                mock_driver = MagicMock()
                mock_driver.current_url = "https://wuzzuf.net"
                return mock_driver

            def __exit__(self, *args):
                active_browsers.remove("selenium")
                events_timeline.append(("exit_selenium", list(active_browsers)))

        with patch.object(job_agent, "SITES", ["linkedin", "wuzzuf"]), \
             patch.object(job_agent, "SEARCH_TERMS", ["Backend"]), \
             patch.object(job_agent, "LOCATION", ["Cairo"]), \
             patch("job_agent.LinkedInSession", return_value=MockLinkedInCtx()), \
             patch("scrapers.selenium_scraper.SeleniumSession", return_value=MockSeleniumCtx()), \
             patch("job_agent.scrape_linkedin_jobs_playwright") as mock_li_jobs, \
             patch("job_agent.scrape_wuzzuf") as mock_wuzzuf:

            mock_li_jobs.return_value = pd.DataFrame([{"title": "LI Job", "job_url": "http://li"}])
            mock_wuzzuf.return_value = pd.DataFrame([{"title": "Wz Job", "job_url": "http://wz"}])

            job_agent.main()

            # Confirm sequence: Playwright entered and exited BEFORE Selenium entered
            event_names = [e[0] for e in events_timeline]
            assert event_names == [
                "enter_playwright",
                "exit_playwright",
                "enter_selenium",
                "exit_selenium",
            ]

            # Verify checkpoint keys
            completed_keys = [c[0][0] for c in mock_checkpoint.mark_completed.call_args_list]
            assert "linkedin:Backend|Cairo" in completed_keys
            assert "selenium:Backend|Cairo" in completed_keys

    @patch("job_agent.process_scraped_batch")
    @patch("job_agent.write_progress")
    @patch("job_agent.ScanCheckpoint")
    @patch("job_agent.cleanup_old_jobs")
    @patch("job_agent.rescore_all_jobs", create=True)
    def test_linkedin_session_failure_falls_back_to_guest_api(
        self, mock_rescore, mock_cleanup, mock_checkpoint_cls, mock_write_progress, mock_batch
    ):
        mock_checkpoint = MagicMock()
        mock_checkpoint.is_completed.return_value = False
        mock_checkpoint_cls.return_value = mock_checkpoint

        class FailingLinkedInCtx:
            def __enter__(self):
                raise RuntimeError("Failed to launch Playwright Chromium")

            def __exit__(self, *args):
                pass

        with patch.object(job_agent, "SITES", ["linkedin"]), \
             patch.object(job_agent, "SEARCH_TERMS", ["Data"]), \
             patch.object(job_agent, "LOCATION", ["Remote"]), \
             patch("job_agent.LinkedInSession", return_value=FailingLinkedInCtx()), \
             patch("scrapers.playwright_scraper.scrape_linkedin_guest_api") as mock_guest_api:

            mock_guest_api.return_value = pd.DataFrame([{"title": "Guest LI Job", "job_url": "http://guest"}])

            job_agent.main()

            # Should have caught the exception and fallen back to guest API
            assert mock_guest_api.called
            mock_checkpoint.mark_completed.assert_called_with("linkedin:Data|Remote")
