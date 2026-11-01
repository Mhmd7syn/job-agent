import sys
import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from core.task_scheduler import (
    sync_autopilot_windows_task,
    get_autopilot_windows_task_status,
    get_scraper_windows_task_status,
    TASK_NAME,
    SCRAPER_TASK_NAME
)
from web.app import app

client = TestClient(app)


class TestTaskScheduler(unittest.TestCase):

    @patch("core.task_scheduler.sys.platform", "win32")
    @patch("core.task_scheduler.subprocess.run")
    def test_sync_disabled_removes_task(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        res = sync_autopilot_windows_task({"enabled": False, "max_runs_per_day": 5})
        self.assertEqual(res["status"], "success")
        self.assertFalse(res["task_enabled"])

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd[0], "schtasks")
        self.assertEqual(cmd[1], "/delete")
        self.assertEqual(cmd[3], TASK_NAME)

    @patch("core.task_scheduler.sys.platform", "win32")
    @patch("core.task_scheduler.subprocess.run")
    def test_sync_enabled_creates_daily_task_with_interval(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        res = sync_autopilot_windows_task({"enabled": True, "max_runs_per_day": 5})
        self.assertEqual(res["status"], "success")
        self.assertTrue(res["task_enabled"])

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd[0], "schtasks")
        self.assertEqual(cmd[1], "/create")
        self.assertIn("/sc", cmd)
        self.assertEqual(cmd[cmd.index("/sc") + 1], "daily")
        self.assertIn("/ri", cmd)
        self.assertEqual(cmd[cmd.index("/ri") + 1], "150")  # 600 / (5 - 1) = 150 min
        self.assertIn("/du", cmd)
        self.assertEqual(cmd[cmd.index("/du") + 1], "10:00")

    @patch("core.task_scheduler.sys.platform", "win32")
    @patch("core.task_scheduler.subprocess.run")
    def test_sync_enabled_single_run(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        res = sync_autopilot_windows_task({"enabled": True, "max_runs_per_day": 1})
        self.assertEqual(res["status"], "success")
        self.assertTrue(res["task_enabled"])

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd[0], "schtasks")
        self.assertEqual(cmd[1], "/create")
        self.assertNotIn("/ri", cmd)

    @patch("core.task_scheduler.sys.platform", "win32")
    @patch("core.task_scheduler.subprocess.run")
    def test_get_autopilot_task_status(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="Status: Ready\nNext Run: Tomorrow", stderr="")
        status = get_autopilot_windows_task_status()
        self.assertTrue(status["exists"])
        self.assertEqual(status["status"], "ready")

    @patch("core.task_scheduler.sys.platform", "win32")
    @patch("core.task_scheduler.subprocess.run")
    def test_get_scraper_task_status(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="Status: Ready\nNext Run: Tomorrow", stderr="")
        status = get_scraper_windows_task_status()
        self.assertTrue(status["exists"])
        self.assertEqual(status["status"], "ready")
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertIn(SCRAPER_TASK_NAME, cmd)

    @patch("web.routers.autopilot.save_profile")
    @patch("web.routers.autopilot.sync_autopilot_windows_task")
    def test_toggle_endpoint_invokes_task_sync(self, mock_sync, mock_save):
        mock_sync.return_value = {"status": "success", "task_enabled": True}
        res = client.post("/api/autopilot/toggle-state", json={"enabled": True})
        self.assertEqual(res.status_code, 200)
        mock_sync.assert_called_once()
        self.assertTrue(mock_sync.call_args[0][0]["enabled"])

    @patch("web.routers.profile.save_profile")
    @patch("web.routers.profile.sync_autopilot_windows_task")
    def test_save_settings_endpoint_invokes_task_sync(self, mock_sync, mock_save):
        mock_sync.return_value = {"status": "success", "task_enabled": False}
        res = client.post("/api/auto-apply/settings", json={"enabled": False, "max_runs_per_day": 3})
        self.assertEqual(res.status_code, 200)
        mock_sync.assert_called_once()
        self.assertFalse(mock_sync.call_args[0][0]["enabled"])

    def test_autopilot_defaults_to_false(self):
        from core.applicant_profile import AutoApplySettings, CandidateProfile, get_default_profile, is_autopilot_enabled
        from core.quota_manager import is_autopilot_enabled as is_quota_autopilot_enabled

        settings = AutoApplySettings()
        self.assertFalse(settings.enabled)

        profile = CandidateProfile()
        self.assertFalse(profile.auto_apply_settings.enabled)

        def_profile = get_default_profile()
        self.assertFalse(def_profile["auto_apply_settings"]["enabled"])

        self.assertFalse(is_autopilot_enabled(def_profile))
        with patch("core.applicant_profile.load_profile", return_value=def_profile):
            self.assertFalse(is_quota_autopilot_enabled())

    @patch("web.routers.autopilot.load_profile")
    def test_autopilot_status_endpoint_defaults_paused(self, mock_load):
        mock_load.return_value = {
            "auto_apply_settings": {
                "enabled": False,
                "batch_size_per_run": 3,
                "max_runs_per_day": 5
            }
        }
        res = client.get("/api/autopilot/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data["is_enabled"])
        self.assertTrue(data["is_paused"])


if __name__ == "__main__":
    unittest.main()
