import os
import sys
import subprocess
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

TASK_NAME = "Job Agent AutoPilot"
SCRAPER_TASK_NAME = "Weekly Job Agent"
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VBS_PATH = os.path.join(BASE_DIR, "scripts", "run_autopilot_silent.vbs")
SCRAPER_VBS_PATH = os.path.join(BASE_DIR, "scripts", "run_silent.vbs")


def sync_autopilot_windows_task(settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Synchronizes Windows Task Scheduler task for AutoPilot according to settings:
    - If auto_apply_settings.enabled is True: creates/updates the task with the configured frequency.
    - If auto_apply_settings.enabled is False: removes the scheduled task.
    """
    if sys.platform != "win32":
        return {"status": "skipped", "message": "Task Scheduler is only supported on Windows."}

    if settings is None:
        from core.applicant_profile import load_profile
        profile = load_profile()
        settings = profile.get("auto_apply_settings", {})

    enabled = bool(settings.get("enabled", False))
    max_runs = int(settings.get("max_runs_per_day", 5))

    if not enabled:
        cmd = ["schtasks", "/delete", "/tn", TASK_NAME, "/f"]
        subprocess.run(cmd, capture_output=True, text=True)
        return {
            "status": "success",
            "task_enabled": False,
            "message": f"Task '{TASK_NAME}' removed from Windows Task Scheduler."
        }

    # Start time: 09:00 AM, Duration: 10 hours (until 07:00 PM)
    vbs_quoted = f'wscript.exe "{VBS_PATH}"'
    if max_runs > 1:
        interval_min = max(15, int(600 / (max_runs - 1)))
        cmd = [
            "schtasks", "/create", "/tn", TASK_NAME,
            "/tr", vbs_quoted,
            "/sc", "daily",
            "/st", "09:00",
            "/ri", str(interval_min),
            "/du", "10:00",
            "/f"
        ]
    else:
        cmd = [
            "schtasks", "/create", "/tn", TASK_NAME,
            "/tr", vbs_quoted,
            "/sc", "daily",
            "/st", "09:00",
            "/f"
        ]

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0:
        return {
            "status": "success",
            "task_enabled": True,
            "max_runs_per_day": max_runs,
            "message": f"Task '{TASK_NAME}' successfully configured in Windows Task Scheduler."
        }
    else:
        err = res.stderr.strip() or res.stdout.strip()
        logger.error(f"Failed to register Windows Task '{TASK_NAME}': {err}")
        return {
            "status": "error",
            "task_enabled": False,
            "message": f"Failed to register task: {err}"
        }


def get_autopilot_windows_task_status() -> Dict[str, Any]:
    """Queries Windows Task Scheduler for current state of AutoPilot task."""
    if sys.platform != "win32":
        return {"exists": False, "status": "unsupported_platform"}

    cmd = ["schtasks", "/query", "/tn", TASK_NAME, "/fo", "LIST"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        return {"exists": False, "status": "not_scheduled"}

    return {
        "exists": True,
        "status": "ready" if "Ready" in res.stdout else "scheduled"
    }


def get_scraper_windows_task_status() -> Dict[str, Any]:
    """Queries Windows Task Scheduler for current state of Scraper task."""
    if sys.platform != "win32":
        return {"exists": False, "status": "unsupported_platform"}

    cmd = ["schtasks", "/query", "/tn", SCRAPER_TASK_NAME, "/fo", "LIST"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        return {"exists": False, "status": "not_scheduled"}

    return {
        "exists": True,
        "status": "ready" if "Ready" in res.stdout else "scheduled"
    }
