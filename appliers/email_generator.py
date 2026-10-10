import os
import json
import logging
import time
import sqlite3
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, '.env'))

from core.applicant_profile import load_profile, get_resume_for_role
from core.cv_parser import extract_text_from_file
from core.database import DB_PATH

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
    "You are a professional job application specialist.\n"
    "Write a concise, tailored email application (100–140 words) in professional business English.\n"
    "Structure the email as follows:\n"
    "1. A direct 1-sentence opening stating interest in the role and core fit.\n"
    "2. 2–3 concise bullet points connecting specific CV achievements to the job requirements.\n"
    "3. A 1-sentence closing mentioning the attached CV and inviting a discussion.\n"
    "Do not invent experience, and do not include a subject line or signature block."
)

EMAIL_USER_PROMPT_TEMPLATE = """Write an email job application for the following position:

Position: {job_title} at {company}
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


def get_job_by_id(job_id: str) -> Optional[Dict[str, Any]]:
    """Fetches job details from the local SQLite database."""
    if not os.path.exists(DB_PATH):
        return None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            d = dict(row)
            if d.get("apply_payload") and isinstance(d["apply_payload"], str):
                try:
                    d["apply_payload"] = json.loads(d["apply_payload"])
                except Exception:
                    d["apply_payload"] = {}
            return d
    except Exception as e:
        logger.error(f"Error fetching job {job_id} from DB: {e}")
    return None


def notify_telegram_candidate(message: str) -> bool:
    """Dispatches real-time notification to candidate on Telegram if configured."""
    try:
        from core.telegram_bot import get_state, send_message, get_bot_token
        from core import config as app_config
        tg_state = get_state()
        chat_id = tg_state.get("chat_id") or getattr(app_config, "TELEGRAM_CHAT_ID", None) or os.getenv("TELEGRAM_CHAT_ID")
        bot_token = get_bot_token() or os.getenv("TELEGRAM_BOT_TOKEN")
        if bot_token and chat_id:
            return send_message(bot_token=bot_token, chat_id=chat_id, text=message)
    except Exception as e:
        logger.debug(f"Failed to notify Telegram candidate: {e}")
    return False


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

    candidate_name = personal_info.get("full_name", "Mohamed Hussein")
    candidate_email = personal_info.get("email", "mhmd7syn.contact@gmail.com")
    candidate_phone = personal_info.get("phone", "")
    personal_signature = auto_apply.get("email_signature_personal", "")

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

    # 1. Deterministic subject line
    default_subject = f"Application: {job_title} – {candidate_name}"
    clean_hint = (subject_hint or "").strip()
    has_specific_code = (
        clean_hint
        and len(clean_hint) >= 3
        and clean_hint.lower() not in [job_title.lower(), "none specified", "none", "application"]
        and not clean_hint.lower().startswith("application for")
    )

    subject = clean_hint if has_specific_code else default_subject

    # 2. Deterministic signature block
    if personal_signature:
        signature = personal_signature.strip()
    else:
        contact_line = candidate_email + (f" | {candidate_phone}" if candidate_phone else "")
        signature = f"Best regards,\n{candidate_name}\n{contact_line}"

    # 3. Simple, transparent prompt formatting
    user_prompt = EMAIL_USER_PROMPT_TEMPLATE.format(
        job_title=job_title,
        company=company,
        location=location or "Not specified",
        description=description[:4000],
        cv_text=cv_text[:6000] if cv_text else "Technical background in software development and data science."
    )

    models_to_try = ['gemini-2.5-flash', 'gemini-flash-lite-latest']
    parsed_draft = None
    last_error = None

    for model_name in models_to_try:
        try:
            from google.genai import types
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

    full_body = f"{parsed_draft.get('body', '').strip()}\n\n{signature}"

    return {
        "status": "success",
        "job_id": job_id,
        "recipient_email": recipient_email,
        "subject": subject,
        "body": full_body,
        "attached_cv": {
            "path": cv_path,
            "filename": os.path.basename(cv_path) if cv_path else None,
            "size_kb": round(os.path.getsize(cv_path) / 1024, 1) if cv_path and os.path.exists(cv_path) else 0,
            "exists": os.path.exists(cv_path) if cv_path else False
        }
    }
