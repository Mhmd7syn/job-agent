import os
import logging
from datetime import datetime
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.database import get_job_by_id, record_job_applied
from core.applicant_profile import load_profile
from appliers.email_generator import generate_email_draft
from appliers.gmail_launcher import prepare_gmail_launch, copy_file_to_clipboard, reveal_in_explorer
from appliers.email_worker import send_smtp_email
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

class TestSmtpRequest(BaseModel):
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    sender_email: Optional[str] = None
    sender_password: Optional[str] = None
    recipient_email: Optional[str] = None


class SendDirectSmtpRequest(BaseModel):
    job_id: str
    recipient: str = Field(default="")
    subject: str = Field(default="")
    body: str = Field(default="")
    cv_path: Optional[str] = None


class MarkAppliedRequest(BaseModel):
    job_id: str
    recipient: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    applied_via: Optional[str] = "smtp_copilot"


@router.post("/api/email/generate-draft")
def generate_email_draft_endpoint(req: EmailDraftRequest):
    draft = generate_email_draft(job_id=req.job_id)
    if draft.get("status") == "error":
        raise HTTPException(status_code=404, detail=draft.get("message", "Job not found"))
    return draft


@router.post("/api/email/test-smtp")
def test_smtp_endpoint(req: Optional[TestSmtpRequest] = None):
    """Sends a verification email to test SMTP connectivity and credentials."""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    profile = load_profile()
    settings = profile.get("auto_apply_settings", {})

    host = (req.smtp_host if req and req.smtp_host else settings.get("smtp_host", "smtp.gmail.com")).strip()
    port = int(req.smtp_port if req and req.smtp_port else settings.get("smtp_port", 465))
    sender = (req.sender_email if req and req.sender_email else settings.get("smtp_email", "")).strip()
    raw_pass = (req.sender_password if req and req.sender_password else settings.get("smtp_app_password", ""))
    password = (raw_pass or "").replace(" ", "").strip()
    recipient = (req.recipient_email if req and req.recipient_email else sender).strip()

    if not sender:
        return {"status": "error", "message": "Sender email is missing. Please enter your email."}
    if not password:
        return {"status": "error", "message": "App Password is missing. Please enter your 16-character App Password."}

    msg = MIMEMultipart("alternative")
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = "Job Agent - Direct SMTP Test Successful 🚀"

    plain_text = f"Hello,\n\nThis is a confirmation test email from Job Agent.\nDirect SMTP is working properly with {host}:{port}!\n\nStatus: Connected & Authenticated"
    html_text = f"""
    <div style="font-family: Arial, sans-serif; line-height: 1.6; color: #1e293b; max-width: 580px; margin: 0 auto; border: 1px solid #e2e8f0; border-radius: 8px; padding: 20px; background: #ffffff;">
        <h2 style="color: #2563eb; margin-top: 0;">🚀 Direct SMTP Test Verified</h2>
        <p>Your SMTP configuration in <b>Job Agent</b> is working properly!</p>
        <div style="background: #f8fafc; border-left: 4px solid #2563eb; padding: 10px 14px; margin: 14px 0; border-radius: 4px; font-size: 13px;">
            <div><b>Sender:</b> {sender}</div>
            <div><b>Host:</b> {host}</div>
            <div><b>Port:</b> {port}</div>
            <div><b>Status:</b> Authenticated & Connected</div>
        </div>
        <p style="color: #64748b; font-size: 12px; margin-bottom: 0;">You can now use direct socket dispatch for 1-click email applications.</p>
    </div>
    """
    msg.attach(MIMEText(plain_text, "plain", "utf-8"))
    msg.attach(MIMEText(html_text, "html", "utf-8"))

    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=15) as server:
                server.login(sender, password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=15) as server:
                server.starttls()
                server.login(sender, password)
                server.send_message(msg)
        return {
            "status": "success",
            "message": f"Test email sent successfully to {recipient} via {host}:{port}!"
        }
    except smtplib.SMTPAuthenticationError:
        return {
            "status": "error",
            "message": f"Authentication failed: Username or App Password rejected by {host}. Please verify your 16-character App Password."
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"SMTP Connection failed: {str(e)}"
        }


@router.post("/api/email/send-direct-smtp")
def send_direct_smtp_endpoint(req: SendDirectSmtpRequest):
    """Sends an email directly via SMTP from the Co-pilot modal."""
    profile = load_profile()
    settings = profile.get("auto_apply_settings", {})

    host = settings.get("smtp_host", "smtp.gmail.com")
    port = int(settings.get("smtp_port", 465))
    sender_email = settings.get("smtp_email", "").strip()
    sender_password = settings.get("smtp_app_password", "").replace(" ", "").strip()

    if not sender_email or not sender_password:
        raise HTTPException(
            status_code=400,
            detail="SMTP credentials not configured. Please set your Sender Email and App Password in Settings."
        )

    if not req.recipient:
        raise HTTPException(status_code=400, detail="Recipient email is required.")

    subject = (req.subject or "").strip()
    if not subject:
        job = get_job_by_id(req.job_id)
        job_title = (job.get("title") or "").strip() if job else ""
        cand_name = profile.get("personal_info", {}).get("full_name", "").strip()
        subject = f"Application: {job_title} – {cand_name}" if (job_title and cand_name) else (f"Application: {job_title}" if job_title else "Job Application")

    success = send_smtp_email(
        smtp_host=host,
        smtp_port=port,
        sender_email=sender_email,
        sender_password=sender_password,
        recipient_email=req.recipient,
        subject=subject,
        body=req.body,
        cv_path=req.cv_path
    )

    if not success:
        raise HTTPException(
            status_code=500,
            detail="Failed to send email via SMTP. Check your connection or credentials in Settings."
        )

    now_str = datetime.now().isoformat()
    record_job_applied(
        job_id=req.job_id,
        channel="sent_email",
        extra_payload={
            "recipient": req.recipient,
            "subject": subject,
            "delivery_method": "smtp_copilot",
            "timestamp": now_str
        }
    )

    return {
        "status": "success",
        "message": f"Email sent directly via SMTP to {req.recipient}!",
        "job_id": req.job_id
    }

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
            "applied_via": req.applied_via or "smtp_copilot",
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
