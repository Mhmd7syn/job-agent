import os
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Any, Optional

from core.database import get_job_by_id, record_job_applied
from core.applicant_profile import load_profile, get_resume_for_role, resolve_contextual_screening
from core.telegram_bot import notify_telegram_candidate

logger = logging.getLogger(__name__)


@dataclass
class ApplicationContext:
    job_id: str
    job_dict: Dict[str, Any]
    candidate_profile: Dict[str, Any]
    job_title: str = ""
    company: str = ""
    location: str = ""
    target_url: str = ""
    resume_path: Optional[str] = None
    resume_exists: bool = False
    resume_filename: Optional[str] = None
    screening_answers: Dict[str, Any] = field(default_factory=dict)
    personal_info: Dict[str, Any] = field(default_factory=dict)
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ApplyResult:
    status: str  # "success", "failed", "skipped", "error"
    job_id: str
    channel: str = ""
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


class BaseApplier(ABC):
    """Abstract base class for all job application dispatchers."""

    channel_name: str = "base"

    def prepare(self, job_id: str) -> Optional[ApplicationContext]:
        """Loads job, profile, role resume, and screening answers into an ApplicationContext."""
        job = get_job_by_id(job_id)
        if not job:
            logger.warning(f"Job not found for ID: {job_id}")
            return None

        title = job.get("title", "")
        company = job.get("company", "")
        location = job.get("location", "")
        job_url = job.get("job_url", "")

        raw_payload = job.get("apply_payload", {})
        if isinstance(raw_payload, str):
            try:
                payload = json.loads(raw_payload)
            except Exception:
                payload = {}
        else:
            payload = raw_payload or {}

        target_url = (
            payload.get("portal_url")
            or payload.get("form_url")
            or payload.get("job_url")
            or job_url
        )

        profile = load_profile()
        personal = profile.get("personal_info", {})
        screening = profile.get("smart_screening", {})
        contextual = resolve_contextual_screening(location)

        screening_answers = {**screening, **contextual}

        resume_path = get_resume_for_role(title)
        resume_exists = bool(resume_path and os.path.exists(resume_path))
        resume_filename = os.path.basename(resume_path) if resume_path else None

        return ApplicationContext(
            job_id=job_id,
            job_dict=job,
            candidate_profile=profile,
            job_title=title,
            company=company,
            location=location,
            target_url=target_url,
            resume_path=resume_path,
            resume_exists=resume_exists,
            resume_filename=resume_filename,
            screening_answers=screening_answers,
            personal_info=personal,
            payload=payload
        )

    @abstractmethod
    def dispatch(self, context: ApplicationContext) -> ApplyResult:
        """Executes the channel-specific application dispatch."""
        pass

    def mark_applied(self, context: ApplicationContext, result: ApplyResult) -> Dict[str, Any]:
        """Updates the database record marking the job as applied."""
        extra_payload = {
            "channel": self.channel_name,
            "status": result.status,
            "message": result.message,
            **result.details
        }
        return record_job_applied(
            job_id=context.job_id,
            channel=self.channel_name,
            extra_payload=extra_payload
        )

    def notify(self, context: ApplicationContext, result: ApplyResult) -> bool:
        """Dispatches real-time candidate notification via Telegram."""
        if result.status == "success":
            msg = f"✓ Applied to '{context.job_title}' at {context.company} via {self.channel_name}."
        else:
            msg = f"⚠️ Auto-Pilot Failed: Could not apply to '{context.job_title}' at {context.company} via {self.channel_name} ({result.message})."
        return notify_telegram_candidate(msg)
