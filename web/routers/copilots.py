import os
import logging
from datetime import datetime
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.database import get_job_by_id, record_job_applied
from appliers.email_generator import generate_email_draft
from appliers.gmail_launcher import prepare_gmail_launch, copy_file_to_clipboard, reveal_in_explorer
from appliers.outlook_launcher import launch_outlook_compose
from appliers.whatsapp_copilot import generate_whatsapp_pitch
from appliers.whatsapp_launcher import launch_whatsapp_desktop
from appliers.easy_apply_copilot import prepare_easy_apply, launch_easy_apply_session, get_session
from appliers.ats_copilot import (
    prepare_ats_application,
    launch_ats_session,
    get_ats_session,
    generate_ats_cover_letter,
    mark_ats_applied
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ==========================================
# Email Co-Pilot & Launchers
# ==========================================

class EmailDraftRequest(BaseModel):
    job_id: str

class OpenInGmailRequest(BaseModel):
    job_id: Optional[str] = None
    recipient: str = Field(default="")
    subject: str = Field(default="")
    body: str = Field(default="")
    cv_path: Optional[str] = None
    open_browser: bool = Field(default=False)

class OpenInOutlookRequest(BaseModel):
    job_id: Optional[str] = None
    recipient: str = Field(default="")
    subject: str = Field(default="")
    body: str = Field(default="")
    raw_body: Optional[str] = None
    cv_path: Optional[str] = None
    personal_signature: Optional[str] = None

class MarkAppliedRequest(BaseModel):
    job_id: str
    recipient: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    applied_via: Optional[str] = "outlook_copilot"


@router.post("/api/email/generate-draft")
def generate_email_draft_endpoint(req: EmailDraftRequest):
    draft = generate_email_draft(job_id=req.job_id)
    if draft.get("status") == "error":
        raise HTTPException(status_code=404, detail=draft.get("message", "Job not found"))
    return draft

@router.post("/api/email/open-in-outlook")
def open_in_outlook_endpoint(req: OpenInOutlookRequest):
    res = launch_outlook_compose(
        recipient=req.recipient,
        subject=req.subject,
        body=req.body,
        cv_path=req.cv_path,
        raw_body=req.raw_body,
        personal_signature=req.personal_signature
    )
    if res.get("status") == "error":
        raise HTTPException(status_code=500, detail=res.get("message", "Failed to launch Outlook"))
    return res

@router.post("/api/email/open-in-gmail")
def open_in_gmail_endpoint(req: OpenInGmailRequest):
    return prepare_gmail_launch(
        recipient=req.recipient,
        subject=req.subject,
        body=req.body,
        cv_path=req.cv_path,
        open_browser=req.open_browser
    )

@router.post("/api/email/copy-cv")
def copy_cv_endpoint(req: Dict[str, Any]):
    cv_path = req.get("cv_path")
    if not cv_path or not os.path.exists(cv_path):
        raise HTTPException(status_code=404, detail="CV file not found")
    copied = copy_file_to_clipboard(cv_path)
    return {"status": "success", "copied": copied, "cv_path": cv_path}

@router.post("/api/email/reveal-cv")
def reveal_cv_endpoint(req: Dict[str, Any]):
    cv_path = req.get("cv_path")
    if not cv_path or not os.path.exists(cv_path):
        raise HTTPException(status_code=404, detail="CV file not found")
    revealed = reveal_in_explorer(cv_path)
    return {"status": "success", "revealed": revealed}

@router.post("/api/email/mark-applied")
def mark_email_applied_endpoint(req: MarkAppliedRequest):
    now_str = datetime.now().isoformat()
    res = record_job_applied(
        job_id=req.job_id,
        channel="sent_email",
        extra_payload={
            "recipient": req.recipient,
            "subject": req.subject,
            "body": req.body,
            "applied_via": req.applied_via or "outlook_copilot",
            "timestamp": now_str
        }
    )
    if res.get("status") == "error":
        raise HTTPException(status_code=500, detail=res.get("message", "Database error"))
    return res


# ============================================
# WhatsApp Co-Pilot & Launchers
# ============================================

class WhatsAppPitchRequest(BaseModel):
    job_id: str

class OpenInWhatsAppDesktopRequest(BaseModel):
    phone: str = Field(default="")
    pitch: str = Field(default="")
    cv_path: Optional[str] = None
    auto_attach: Optional[bool] = True

class MarkWhatsAppAppliedRequest(BaseModel):
    job_id: str
    phone: Optional[str] = None
    pitch: Optional[str] = None
    applied_via: Optional[str] = "whatsapp_desktop"


@router.post("/api/whatsapp/generate-pitch")
def generate_whatsapp_pitch_endpoint(req: WhatsAppPitchRequest):
    pitch_data = generate_whatsapp_pitch(job_id=req.job_id)
    if pitch_data.get("status") == "error":
        raise HTTPException(status_code=404, detail=pitch_data.get("message", "Job not found"))
    return pitch_data

@router.post("/api/whatsapp/open-in-desktop")
def open_in_whatsapp_desktop_endpoint(req: OpenInWhatsAppDesktopRequest):
    res = launch_whatsapp_desktop(
        phone=req.phone,
        pitch=req.pitch,
        cv_path=req.cv_path,
        auto_attach=req.auto_attach if req.auto_attach is not None else True
    )
    if res.get("status") == "error":
        raise HTTPException(status_code=500, detail=res.get("message", "Failed to launch WhatsApp Desktop"))
    return res

@router.post("/api/whatsapp/copy-cv")
def copy_whatsapp_cv_endpoint(req: Dict[str, Any]):
    cv_path = req.get("cv_path")
    if not cv_path or not os.path.exists(cv_path):
        raise HTTPException(status_code=404, detail="CV file not found")
    copied = copy_file_to_clipboard(cv_path)
    return {"status": "success", "copied": copied, "cv_path": cv_path}

@router.post("/api/whatsapp/reveal-cv")
def reveal_whatsapp_cv_endpoint(req: Dict[str, Any]):
    cv_path = req.get("cv_path")
    if not cv_path or not os.path.exists(cv_path):
        raise HTTPException(status_code=404, detail="CV file not found")
    revealed = reveal_in_explorer(cv_path)
    return {"status": "success", "revealed": revealed}

@router.post("/api/whatsapp/mark-applied")
def mark_whatsapp_applied_endpoint(req: MarkWhatsAppAppliedRequest):
    now_str = datetime.now().isoformat()
    res = record_job_applied(
        job_id=req.job_id,
        channel="sent_whatsapp",
        extra_payload={
            "phone": req.phone,
            "pitch": req.pitch,
            "applied_via": req.applied_via or "whatsapp_desktop",
            "timestamp": now_str
        }
    )
    if res.get("status") == "error":
        raise HTTPException(status_code=500, detail=res.get("message", "Database error"))
    return res


# ============================================
# Easy Apply Co-Pilot & Assisted Session
# ============================================

class EasyApplyPrepareRequest(BaseModel):
    job_id: str

class EasyApplyLaunchRequest(BaseModel):
    job_id: str
    headed: Optional[bool] = True

class MarkEasyApplyAppliedRequest(BaseModel):
    job_id: str
    applied_via: Optional[str] = "easy_apply_copilot"


@router.post("/api/easy-apply/prepare")
def easy_apply_prepare_endpoint(req: EasyApplyPrepareRequest):
    data = prepare_easy_apply(job_id=req.job_id)
    if data.get("status") == "error":
        raise HTTPException(status_code=404, detail=data.get("message", "Job not found"))
    return data

@router.post("/api/easy-apply/launch-session")
def easy_apply_launch_session_endpoint(req: EasyApplyLaunchRequest):
    res = launch_easy_apply_session(job_id=req.job_id, headed=req.headed if req.headed is not None else True)
    if res.get("status") == "error":
        raise HTTPException(status_code=500, detail=res.get("message", "Failed to launch Easy Apply session"))
    return res

@router.get("/api/easy-apply/status/{job_id}")
def easy_apply_status_endpoint(job_id: str):
    session = get_session(job_id)
    if not session:
        return {"status": "idle", "job_id": job_id, "current_step": "Not started", "logs": []}
    return session.to_dict()

@router.post("/api/easy-apply/mark-applied")
def mark_easy_apply_applied_endpoint(req: MarkEasyApplyAppliedRequest):
    now_str = datetime.now().isoformat()
    res = record_job_applied(
        job_id=req.job_id,
        channel="sent_easy_apply",
        extra_payload={
            "applied_via": req.applied_via or "easy_apply_copilot",
            "timestamp": now_str
        }
    )
    if res.get("status") == "error":
        raise HTTPException(status_code=500, detail=res.get("message", "Database error"))
    return res


# ============================================
# ATS & Web Forms Co-Pilot
# ============================================

class AtsPrepareRequest(BaseModel):
    job_id: str

class AtsLaunchRequest(BaseModel):
    job_id: str
    headed: Optional[bool] = True

class AtsCoverLetterRequest(BaseModel):
    job_id: str

class MarkAtsAppliedRequest(BaseModel):
    job_id: str
    applied_via: Optional[str] = "ats_copilot"


@router.post("/api/ats/prepare")
def ats_prepare_endpoint(req: AtsPrepareRequest):
    data = prepare_ats_application(job_id=req.job_id)
    if data.get("status") == "error":
        raise HTTPException(status_code=404, detail=data.get("message", "Job not found"))
    return data

@router.post("/api/ats/launch-session")
def ats_launch_session_endpoint(req: AtsLaunchRequest):
    res = launch_ats_session(job_id=req.job_id, headed=req.headed if req.headed is not None else True)
    if res.get("status") == "error":
        raise HTTPException(status_code=500, detail=res.get("message", "Failed to launch ATS session"))
    return res

@router.get("/api/ats/status/{job_id}")
def ats_status_endpoint(job_id: str):
    session = get_ats_session(job_id)
    if not session:
        return {"status": "idle", "job_id": job_id, "current_step": "Not started", "logs": []}
    return session.to_dict()

@router.post("/api/ats/generate-cover-letter")
def ats_cover_letter_endpoint(req: AtsCoverLetterRequest):
    from core.applicant_profile import get_resume_for_role
    from core.cv_parser import extract_text_from_file

    job = get_job_by_id(req.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    cv_path = get_resume_for_role(job.get("title", ""))
    cv_text = ""
    if cv_path and os.path.exists(cv_path):
        try:
            cv_text = extract_text_from_file(cv_path)
        except Exception:
            pass
    cl = generate_ats_cover_letter(
        job_title=job.get("title", ""),
        company=job.get("company", ""),
        location=job.get("location", ""),
        job_description=job.get("description", ""),
        cv_text=cv_text
    )
    return {"status": "success", "job_id": req.job_id, "cover_letter": cl}

@router.post("/api/ats/mark-applied")
def mark_ats_applied_endpoint(req: MarkAtsAppliedRequest):
    res = mark_ats_applied(job_id=req.job_id)
    if res.get("status") == "error":
        raise HTTPException(status_code=500, detail=res.get("message", "Failed to mark ATS job as applied"))
    return res
