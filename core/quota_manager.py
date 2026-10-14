import os
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUTOPILOT_STATE_FILE = os.path.join(BASE_DIR, "output", "autopilot_state.json")
logger = logging.getLogger(__name__)


class DailyQuotaManager:
    """Manages persistent Auto-Pilot rate limiting, daily counters, and activity logging."""

    def __init__(self, state_file: str = AUTOPILOT_STATE_FILE):
        self.state_file = state_file

    def get_state(self) -> Dict[str, Any]:
        """Loads state, resetting daily counters if a new calendar day has started."""
        today_str = datetime.now().strftime("%Y-%m-%d")
        default_state = {
            "last_run_date": today_str,
            "daily_runs_count": 0,
            "emails_sent_today": 0,
            "whatsapp_sent_today": 0,
            "easy_apply_sent_today": 0,
            "ats_sent_today": 0,
            "total_applied_all_time": 0,
            "recent_logs": []
        }

        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    state = json.load(f)
                if state.get("last_run_date") != today_str:
                    state["last_run_date"] = today_str
                    state["daily_runs_count"] = 0
                    state["emails_sent_today"] = 0
                    state["whatsapp_sent_today"] = 0
                    state["easy_apply_sent_today"] = 0
                    state["ats_sent_today"] = 0
                for k, v in default_state.items():
                    if k not in state:
                        state[k] = v
                return state
            except Exception as e:
                logger.warning(f"Error loading autopilot state from {self.state_file}: {e}")

        return default_state

    def save_state(self, state: Dict[str, Any]) -> None:
        """Persists state atomically."""
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            temp_file = self.state_file + ".tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
            os.replace(temp_file, self.state_file)
        except Exception as e:
            logger.error(f"Error saving autopilot state to {self.state_file}: {e}")

    def log_activity(self, message: str, state: Optional[Dict[str, Any]] = None) -> None:
        """Appends timestamped log entry to state."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] {message}"
        logger.info(f"[AutoPilot] {message}")
        if state is not None:
            if "recent_logs" not in state:
                state["recent_logs"] = []
            state["recent_logs"].append(entry)
            state["recent_logs"] = state["recent_logs"][-40:]

    def is_daily_run_limit_reached(self, max_runs_per_day: int, state: Optional[Dict[str, Any]] = None) -> bool:
        """Checks if daily run limit has been reached."""
        current_state = state if state is not None else self.get_state()
        return current_state.get("daily_runs_count", 0) >= max_runs_per_day

    def record_run(self, state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Increments daily run count and persists state."""
        current_state = state if state is not None else self.get_state()
        current_state["daily_runs_count"] = current_state.get("daily_runs_count", 0) + 1
        self.save_state(current_state)
        return current_state

    def record_applied(self, channel: str, count: int = 1, state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Increments channel applied counter and total applied all-time."""
        current_state = state if state is not None else self.get_state()
        key = f"{channel}_sent_today"
        current_state[key] = current_state.get(key, 0) + count
        current_state["total_applied_all_time"] = current_state.get("total_applied_all_time", 0) + count
        self.save_state(current_state)
        return current_state


# Global singleton instance & convenience wrappers
_default_manager = DailyQuotaManager()

def get_autopilot_state() -> Dict[str, Any]:
    return _default_manager.get_state()

def save_autopilot_state(state: Dict[str, Any]) -> None:
    _default_manager.save_state(state)

def log_autopilot_activity(message: str, state: Optional[Dict[str, Any]] = None) -> None:
    _default_manager.log_activity(message, state)
