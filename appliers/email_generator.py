import os
import json
import logging
import time
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, '.env'))
except ImportError:
    pass

from core.applicant_profile import load_profile, get_resume_for_role
from core.cv_parser import extract_text_from_file
from core.database import get_job_by_id
from core.email_signature import get_signature_text, get_signature_html
from core.job_utils import is_confidential_company

logger = logging.getLogger(__name__)

# Gemini client initialization
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    try:
        from core.config import decrypt_value
        decrypted_key = decrypt_value(GEMINI_API_KEY)
    except Exception:
        decrypted_key = GEMINI_API_KEY
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=decrypted_key)
    except Exception as e:
        logger.warning(f"Failed to initialize google-genai client: {e}")
        client = None
else:
    client = None


# Clean, centralized prompt templates (easy to inspect, monitor, and tweak)
EMAIL_SYSTEM_PROMPT = (
    "You are a job application specialist drafting a direct, natural outreach email from a candidate to a recruiter or hiring manager.\n"
    "Write a concise email (90–130 words) in clear, professional, human English.\n\n"
    "TONE & STYLE:\n"
    "- Sound like a real, competent professional speaking directly to another professional—practical, confident, and grounded.\n"
    "- Use natural contractions (I'm, I've) where appropriate.\n"
    "- Use plain, direct verbs (built, worked with, shipped, led) instead of resume buzzwords (spearheaded, leveraged, orchestrated).\n"
    "- BANNED IDIOMS & CLICHÉS: Do NOT use colloquial idioms or slang. Never use AI cliches like 'I hope this email finds you well', 'testament', 'delve', 'plethora', 'synergy', 'thrilled to apply', 'esteemed team', or 'poised to'.\n\n"
    "SECTIONS & STRUCTURE:\n"
    "1. Salutation: Professional greeting on its own line (e.g., 'Dear Hiring Team,').\n"
    "2. Opening: Direct statement of application (e.g., 'I\\'m reaching out to apply for the [Role] position at [Company].' or omit company if confidential/unspecified), followed by a natural transition to the highlights (e.g., 'A few key highlights of how my background aligns with the role:').\n"
    "3. Key Highlights: 2–3 concise bullet points connecting real CV technical accomplishments and tools to the job needs.\n"
    "4. Closing: Exactly 1 low-friction sentence mentioning the attached CV (e.g., 'I\\'ve attached my resume for your review and would welcome the opportunity to discuss my fit.').\n\n"
    "CRITICAL FORMATTING:\n"
    "- Every section MUST be separated by a blank line (double newline).\n"
    "- Bullet points must each be on their own line with bullet markers (• or -).\n"
    "- Do not invent skills or experience not present in the CV.\n"
    "- Never refer to the company as 'Confidential' or use placeholder names. If the company is omitted or confidential, refer only to the position.\n"
    "- Do not include a subject line or signature block (signature will be added manually; output only the email body)."
)

EMAIL_USER_PROMPT_TEMPLATE = """Write an email job application for the following position:

Position: {position}
Location: {location}

Job Description:
\"\"\"
{description}
\"\"\"

Candidate Resume Text:
\"\"\"
{cv_text}
\"\"\"
"""


class EmailDraftSchema(BaseModel):
    body: str = Field(description="The concise email application body from greeting to closing statement, without signature block.")



from core.telegram_bot import notify_telegram_candidate


def generate_email_draft(
    job_id: Optional[str] = None,
    job_data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Generates a personalized, tailored email application draft for an active job opening.
    Uses Gemini API with candidate CV context and personal signature.
    """
    if not job_data and job_id:
        job_data = get_job_by_id(job_id)

    if not job_data:
        return {"status": "error", "message": f"Job not found for ID: {job_id}"}

    job_title = job_data.get("title", "Position")
    company = job_data.get("company", "Company")
    location = job_data.get("location", "")
    description = job_data.get("description", "")

    apply_payload = job_data.get("apply_payload", {})
    if isinstance(apply_payload, str):
        try:
            apply_payload = json.loads(apply_payload)
        except Exception:
            apply_payload = {}

    recipient_email = apply_payload.get("recipient_email", "")
    subject_hint = apply_payload.get("subject_hint", "")

    # Load candidate profile
    profile = load_profile()
    personal_info = profile.get("personal_info", {})
    auto_apply = profile.get("auto_apply_settings", {})

    candidate_name = personal_info.get("full_name", "").strip()
    signature_text = get_signature_text(profile)
    signature_html = get_signature_html(profile)

    # Locate role-specific resume PDF
    cv_path = get_resume_for_role(job_title)
    cv_text = ""
    if cv_path and os.path.exists(cv_path):
        try:
            cv_text = extract_text_from_file(cv_path)
        except Exception as e:
            logger.warning(f"Could not extract CV text from {cv_path}: {e}")

    # If no Gemini client, discard applying and notify via Telegram
    if not client:
        err_msg = "Gemini AI client is not initialized or API key is missing."
        logger.warning(f"Discarding email application for '{job_title}' at '{company}': {err_msg}")
        notify_telegram_candidate(
            f"⚠️ Discarded Email Application: AI is unavailable for '{job_title}' at {company}."
        )
        return {
            "status": "error",
            "reason": "ai_unavailable",
            "message": f"AI unavailable ({err_msg}). Application for '{job_title}' discarded.",
            "job_id": job_id,
            "recipient_email": recipient_email
        }

    is_confidential = is_confidential_company(company)
    target_position = job_title if is_confidential else f"{job_title} at {company}"

    # 1. Deterministic subject line
    default_subject = f"Application: {job_title} – {candidate_name}" if candidate_name else f"Application: {job_title}"
    clean_hint = (subject_hint or "").strip()
    has_specific_code = (
        clean_hint
        and len(clean_hint) >= 3
        and clean_hint.lower() not in [job_title.lower(), "none specified", "none", "application"]
        and not clean_hint.lower().startswith("application for")
    )

    subject = clean_hint if has_specific_code else default_subject

    # 2. Deterministic signature block from configuration
    signature = signature_text

    # 3. Simple, transparent prompt formatting
    user_prompt = EMAIL_USER_PROMPT_TEMPLATE.format(
        position=target_position,
        location=location or "Not specified",
        description=description[:4000],
        cv_text=cv_text[:6000] if cv_text else "Technical background in software development and data science."
    )

    models_to_try = ['gemini-2.5-flash', 'gemini-flash-lite-latest']
    parsed_draft = None
    last_error = None

    for model_name in models_to_try:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=EMAIL_SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=EmailDraftSchema,
                    temperature=0.2
                )
            )
            parsed_draft = json.loads(response.text)
            break
        except Exception as e:
            last_error = str(e)
            logger.warning(f"Gemini draft generation failed with model {model_name}: {e}")
            time.sleep(1)

    if not parsed_draft:
        err_msg = f"All Gemini models failed ({last_error})."
        logger.warning(f"Discarding email application for '{job_title}' at '{company}': {err_msg}")
        notify_telegram_candidate(
            f"⚠️ Discarded Email Application: AI generation failed for '{job_title}' at {company} ({last_error})."
        )
        return {
            "status": "error",
            "reason": "ai_unavailable",
            "message": f"AI generation failed ({err_msg}). Application for '{job_title}' discarded.",
            "job_id": job_id,
            "recipient_email": recipient_email
        }

    raw_body = parsed_draft.get('body', '').strip()
    full_body = f"{raw_body}\n\n{signature}" if signature else raw_body

    return {
        "status": "success",
        "job_id": job_id,
        "recipient_email": recipient_email,
        "subject": subject,
        "body": full_body,
        "raw_ai_body": raw_body,
        "personal_signature": signature_html or signature,
        "attached_cv": {
            "path": cv_path,
            "filename": os.path.basename(cv_path) if cv_path else None,
            "size_kb": round(os.path.getsize(cv_path) / 1024, 1) if cv_path and os.path.exists(cv_path) else 0,
            "exists": os.path.exists(cv_path) if cv_path else False
        }
    }
