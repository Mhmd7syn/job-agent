import os
import json
import re
import logging
import time
import sqlite3
import urllib.parse
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
        logger.warning(f"Failed to initialize google-genai client for WhatsApp Co-Pilot: {e}")
        client = None
else:
    client = None


class WhatsAppPitchSchema(BaseModel):
    pitch: str = Field(
        description="The concise, high-impact recruiter message strictly in professional English. "
                    "Includes greeting, introduction, 2-3 brief bullet highlights from the candidate's CV matching the job, "
                    "an explicit note stating that the CV is attached as a PDF, and a polite sign-off."
    )
    key_highlights_used: list[str] = Field(
        default=[],
        description="Bullet points of real skills or projects highlighted from the CV."
    )


def normalize_phone_number(raw_phone: str) -> str:
    """
    Normalizes Egyptian, Gulf, and international numbers into clean E.164 digits without leading +.
    e.g. '01097748566' -> '201097748566'
         '+20 10 9774 8566' -> '201097748566'
         '0501234567' -> '966501234567'
    """
    if not raw_phone:
        return ""
    digits = re.sub(r'\D', '', str(raw_phone))

    # Egyptian local format (11 digits starting with 01)
    if len(digits) == 11 and digits.startswith("01"):
        return "20" + digits[1:]

    # Egyptian with country code (12 digits starting with 201)
    if len(digits) == 12 and digits.startswith("201"):
        return digits

    # Egyptian with 0020 prefix
    if len(digits) == 14 and digits.startswith("00201"):
        return digits[2:]

    # Saudi format (starting with 05 -> 9665)
    if len(digits) == 10 and digits.startswith("05"):
        return "966" + digits[1:]
    if len(digits) == 12 and digits.startswith("9665"):
        return digits

    # UAE format (starting with 05 -> 9715)
    if len(digits) == 10 and digits.startswith("05"):
        return "971" + digits[1:]
    if len(digits) == 12 and digits.startswith("9715"):
        return digits

    # General international number (10 to 15 digits)
    if 10 <= len(digits) <= 15:
        return digits

    return digits


def build_whatsapp_desktop_url(phone: str, text: str) -> str:
    """Builds native Windows WhatsApp Desktop protocol URL."""
    clean_phone = normalize_phone_number(phone)
    encoded_text = urllib.parse.quote(text)
    if clean_phone:
        return f"whatsapp://send?phone={clean_phone}&text={encoded_text}"
    return f"whatsapp://send?text={encoded_text}"


def build_wa_me_url(phone: str, text: str) -> str:
    """Builds standard wa.me web redirect link."""
    clean_phone = normalize_phone_number(phone)
    encoded_text = urllib.parse.quote(text)
    if clean_phone:
        return f"https://wa.me/{clean_phone}?text={encoded_text}"
    return f"https://wa.me/?text={encoded_text}"


def build_whatsapp_web_url(phone: str, text: str) -> str:
    """Builds direct WhatsApp Web link."""
    clean_phone = normalize_phone_number(phone)
    encoded_text = urllib.parse.quote(text)
    if clean_phone:
        return f"https://web.whatsapp.com/send?phone={clean_phone}&text={encoded_text}"
    return f"https://web.whatsapp.com/send?text={encoded_text}"


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


def generate_fallback_pitch(
    job_title: str,
    company: str,
    candidate_name: str,
    cv_path: Optional[str] = None,
    candidate_phone: str = "",
    candidate_email: str = "",
    linkedin_url: str = ""
) -> Dict[str, Any]:
    """Generates a reliable, professional English pitch when Gemini AI is unavailable."""
    comp_display = company if company and company.lower() != "unknown" else "the Hiring Team"

    lines = [
        f"Hello Hiring Team at {comp_display},",
        f"I am reaching out regarding the {job_title} opportunity.",
        f"I bring relevant technical background and hands-on experience that align closely with the role's requirements.",
        "I have attached my tailored resume (PDF) for your review.",
        f"Looking forward to connecting with you.",
        f"\nBest regards,\n{candidate_name}"
    ]

    contact_bits = []
    if candidate_phone:
        contact_bits.append(candidate_phone)
    if candidate_email:
        contact_bits.append(candidate_email)
    if linkedin_url:
        contact_bits.append(linkedin_url)

    if contact_bits:
        lines.append(" | ".join(contact_bits))

    pitch_text = "\n\n".join(lines[:4]) + "\n\n" + lines[4] + "\n" + lines[5]
    if len(lines) > 6:
        pitch_text += "\n" + lines[6]

    return {
        "status": "success",
        "engine": "heuristic_fallback",
        "pitch": pitch_text.strip(),
        "key_highlights_used": [
            "Tailored background matching target role",
            "Attached comprehensive CV"
        ],
        "attached_cv": {
            "path": cv_path,
            "filename": os.path.basename(cv_path) if cv_path else None,
            "size_kb": round(os.path.getsize(cv_path) / 1024, 1) if cv_path and os.path.exists(cv_path) else 0,
            "exists": os.path.exists(cv_path) if cv_path else False
        }
    }


def generate_whatsapp_pitch(
    job_id: Optional[str] = None,
    job_data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Generates a tailored, high-converting recruiter WhatsApp outreach pitch strictly in English.
    Extracts candidate profile context and matched role CV text from OneDrive.
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

    phone = apply_payload.get("phone", "")
    whatsapp_url = apply_payload.get("whatsapp_url", "")
    normalized_phone = normalize_phone_number(phone)

    # Load candidate profile
    profile = load_profile()
    personal_info = profile.get("personal_info", {})
    candidate_name = personal_info.get("full_name", "Mohamed Hussein")
    candidate_email = personal_info.get("email", "mhmd7syn.contact@gmail.com")
    candidate_phone = personal_info.get("phone", "+201097344958")
    linkedin_url = personal_info.get("linkedin_url", "https://linkedin.com/in/Mhmd7syn")

    # Locate role-specific resume PDF
    cv_path = get_resume_for_role(job_title)
    cv_text = ""
    if cv_path and os.path.exists(cv_path):
        try:
            cv_text = extract_text_from_file(cv_path)
        except Exception as e:
            logger.warning(f"Could not extract CV text from {cv_path}: {e}")

    # If no Gemini client, use deterministic fallback
    if not client:
        result = generate_fallback_pitch(
            job_title=job_title,
            company=company,
            candidate_name=candidate_name,
            cv_path=cv_path,
            candidate_phone=candidate_phone,
            candidate_email=candidate_email,
            linkedin_url=linkedin_url
        )
        result["phone"] = normalized_phone
        result["whatsapp_url"] = whatsapp_url or (f"https://wa.me/{normalized_phone}" if normalized_phone else "")
        result["desktop_url"] = build_whatsapp_desktop_url(normalized_phone, result["pitch"])
        result["wa_me_url"] = build_wa_me_url(normalized_phone, result["pitch"])
        result["job_id"] = job_id
        return result

    system_instruction = (
        "You are an elite tech talent agent and recruiter outreach specialist.\n"
        "Your task is to craft a concise, compelling, high-converting WhatsApp message to a recruiter or hiring manager.\n\n"
        "CRITICAL RULES:\n"
        "1. STRICTLY ENGLISH LANGUAGE:\n"
        "   - ALWAYS write the message in fluent, idiomatic, professional business English.\n"
        "   - Even if the job description or post is in Arabic or mentions an Arab country, write ONLY in English.\n"
        "2. CONCISE & READABLE ON MOBILE (under 100 words total):\n"
        "   - WhatsApp messages must be quick to scan on mobile screens.\n"
        "   - Start with a polite greeting (e.g. 'Hello Hiring Team at {company},' or 'Dear {company} Team,').\n"
        "   - Mention the target role ({job_title}).\n"
        "   - Include 2 short bullet points summarizing matching technical skills or experience directly from the candidate's CV.\n"
        "   - Explicitly mention that the CV/resume PDF is attached.\n"
        "   - Sign off with candidate's full name, email, phone, and LinkedIn profile.\n"
        "3. STRICT TRUTHFULNESS & FACTUAL GROUNDING:\n"
        "   - Only mention real technologies, skills, or projects present in the candidate's CV.\n"
        "   - NEVER hallucinate fake experience or ungrounded credentials.\n"
    )

    user_prompt = f"""Generate a WhatsApp outreach pitch based on the following details:

---
### TARGET JOB DETAILS:
- Job Title: {job_title}
- Company: {company}
- Location: {location}
- Job Description:
\"\"\"
{description[:4000]}
\"\"\"

---
### CANDIDATE DETAILS:
- Full Name: {candidate_name}
- Email: {candidate_email}
- Phone: {candidate_phone}
- LinkedIn: {linkedin_url}

---
### CANDIDATE RESUME TEXT:
\"\"\"
{cv_text[:6000] if cv_text else "Technical background in software development, data science, machine learning, and training."}
\"\"\"
"""

    # Retry loop with exponential backoff
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    response_schema=WhatsAppPitchSchema,
                    temperature=0.2,
                ),
            )
            parsed = json.loads(response.text)
            pitch_text = parsed.get("pitch", "").strip()
            highlights = parsed.get("key_highlights_used", [])

            return {
                "status": "success",
                "engine": "gemini-2.5-flash",
                "pitch": pitch_text,
                "key_highlights_used": highlights,
                "phone": normalized_phone,
                "whatsapp_url": whatsapp_url or (f"https://wa.me/{normalized_phone}" if normalized_phone else ""),
                "desktop_url": build_whatsapp_desktop_url(normalized_phone, pitch_text),
                "wa_me_url": build_wa_me_url(normalized_phone, pitch_text),
                "attached_cv": {
                    "path": cv_path,
                    "filename": os.path.basename(cv_path) if cv_path else None,
                    "size_kb": round(os.path.getsize(cv_path) / 1024, 1) if cv_path and os.path.exists(cv_path) else 0,
                    "exists": os.path.exists(cv_path) if cv_path else False
                },
                "job_id": job_id
            }
        except Exception as e:
            err_str = str(e).lower()
            if "429" in err_str or "quota" in err_str or "resource_exhausted" in err_str:
                wait_time = 2 ** attempt
                logger.warning(f"Rate limited by Gemini on WhatsApp pitch attempt {attempt + 1}. Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                logger.error(f"Gemini generation error on WhatsApp pitch: {e}")
                break

    # Fallback if AI generation failed or timed out
    logger.info(f"Falling back to heuristic pitch generation for job: {job_title}")
    result = generate_fallback_pitch(
        job_title=job_title,
        company=company,
        candidate_name=candidate_name,
        cv_path=cv_path,
        candidate_phone=candidate_phone,
        candidate_email=candidate_email,
        linkedin_url=linkedin_url
    )
    result["phone"] = normalized_phone
    result["whatsapp_url"] = whatsapp_url or (f"https://wa.me/{normalized_phone}" if normalized_phone else "")
    result["desktop_url"] = build_whatsapp_desktop_url(normalized_phone, result["pitch"])
    result["wa_me_url"] = build_wa_me_url(normalized_phone, result["pitch"])
    result["job_id"] = job_id
    return result
