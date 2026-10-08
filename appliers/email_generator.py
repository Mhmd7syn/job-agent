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


class EmailDraftSchema(BaseModel):
    subject: str = Field(description="The exact email subject line. Follows any subject hints or codes specified in the job posting, otherwise 'Application for {job_title} - {candidate_full_name}'.")
    salutation: str = Field(description="Formal salutation, e.g. 'Dear Hiring Team at {company},' or 'Dear Hiring Manager,'.")
    body: str = Field(description="The email body in English, including salutation, introductory hook, 2-3 bullet highlights from CV matching JD requirements, CV attachment reference, and sign-off ('Best regards,\n{candidate_full_name}'). Do NOT add synthetic footers, phone numbers, or social links at the end.")
    key_highlights_used: list[str] = Field(default=[], description="Bullet points of real skills or projects highlighted from the CV.")


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


def append_signature_safely(body: str, signature: str, candidate_name: str) -> str:
    """
    Appends the personal signature to the email body cleanly,
    preventing duplicate 'Best regards' or sign-offs.
    """
    if not signature or not signature.strip():
        return body.strip()

    body = body.strip()
    sig = signature.strip()

    closings = ("best regards", "warm regards", "kind regards", "regards", "sincerely", "thank you", "thanks")
    sig_lower = sig.lower()
    sig_has_closing = any(sig_lower.startswith(c) for c in closings)

    body_lines = [line.strip() for line in body.split("\n")]
    while body_lines and not body_lines[-1]:
        body_lines.pop()

    if sig_has_closing and body_lines:
        name_parts = [p.lower() for p in candidate_name.split() if len(p) > 2]
        last_line_is_name = any(part in body_lines[-1].lower() for part in name_parts)

        if len(body_lines) >= 2 and last_line_is_name:
            if any(body_lines[-2].lower().startswith(c) for c in closings):
                body_lines = body_lines[:-2]
        elif any(body_lines[-1].lower().startswith(c) for c in closings):
            body_lines = body_lines[:-1]

        clean_body = "\n".join(body_lines).strip()
        return f"{clean_body}\n\n{sig}"

    return f"{body}\n\n{sig}"


def generate_fallback_draft(
    job_title: str,
    company: str,
    subject_hint: str,
    candidate_name: str,
    cv_path: Optional[str],
    personal_signature: str = ""
) -> Dict[str, Any]:
    """Generates a reliable, clean English template when Gemini AI is unavailable."""
    subject = subject_hint if subject_hint and len(subject_hint) > 3 else f"Application for {job_title} - {candidate_name}"
    comp_display = company if company and company.lower() != "unknown" else "the Hiring Team"

    body_paragraphs = [
        f"Dear Hiring Team at {comp_display},",
        f"I am writing to express my strong interest in the {job_title} position. With my relevant background and technical experience, I am confident in my ability to deliver immediate value to your team.",
        "My tailored curriculum vitae is attached as a PDF for your detailed review, highlighting my core competencies, recent projects, and accomplishments.",
        "I would welcome the opportunity to discuss how my qualifications align with your requirements. Thank you for your time and consideration.",
        f"Best regards,\n{candidate_name}"
    ]

    base_body = "\n\n".join(body_paragraphs)
    full_body = append_signature_safely(base_body, personal_signature, candidate_name)

    return {
        "status": "success",
        "engine": "heuristic_fallback",
        "subject": subject,
        "salutation": f"Dear Hiring Team at {comp_display},",
        "body": full_body,
        "raw_ai_body": base_body,
        "key_highlights_used": ["Tailored background matching target role", "Attached comprehensive CV"],
        "attached_cv": {
            "path": cv_path,
            "filename": os.path.basename(cv_path) if cv_path else None,
            "size_kb": round(os.path.getsize(cv_path) / 1024, 1) if cv_path and os.path.exists(cv_path) else 0,
            "exists": os.path.exists(cv_path) if cv_path else False
        },
        "personal_signature": personal_signature,
        "has_personal_signature": bool(personal_signature and personal_signature.strip())
    }


def generate_email_draft(
    job_id: Optional[str] = None,
    job_data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Generates a personalized, high-converting cold email draft for a given job.
    Uses Gemini API with candidate CV context and appends user's 'personal' signature.
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

    # If no Gemini client, use fallback
    if not client:
        result = generate_fallback_draft(
            job_title, company, subject_hint, candidate_name, cv_path, personal_signature
        )
        result["recipient_email"] = recipient_email
        result["job_id"] = job_id
        return result

    # Build Gemini system prompt and user prompt
    system_instruction = (
        "You are an elite career strategist, executive recruiter, and cold outreach specialist.\n"
        "Your goal is to craft a concise, compelling, high-converting cold email application.\n\n"
        "CRITICAL RULES:\n"
        "1. STRICTLY ENGLISH LANGUAGE:\n"
        "   - ALWAYS write the email application in fluent, idiomatic, professional business English.\n"
        "   - Even if the job description contains Arabic or is based in an Arab country, NEVER write the email in Arabic.\n"
        "2. STRICT TRUTHFULNESS & ZERO HALLUCINATIONS:\n"
        "   - Only reference skills, projects, tools, degrees, or metrics that EXPLICITLY appear in the Candidate CV text provided.\n"
        "   - NEVER invent past companies, certifications, or accomplishments not in the candidate's CV.\n"
        "3. CONCISE & PUNCHY (120–160 words total):\n"
        "   - Recruiters spend less than 15 seconds reading cold emails.\n"
        "   - Use short paragraphs and 2–3 targeted bullet points connecting specific CV achievements directly to the job requirements.\n"
        "4. SUBJECT LINE:\n"
        "   - If the job posting provided a required subject line or code (e.g. '108S-CS' or 'CS Trainer – [Full Name]'), follow that exact format.\n"
        f"   - Otherwise, default to: 'Application for {job_title} - {candidate_name}'.\n"
        "5. CALL TO ACTION & SIGN-OFF:\n"
        "   - Explicitly mention that the tailored CV is attached as a PDF for their review.\n"
        f"   - Conclude with a brief closing line: 'Best regards,\n{candidate_name}'.\n"
        "   - Do NOT add synthetic contact footers or placeholder phone/social links at the end, as the candidate's saved personal email signature will be appended directly below."
    )

    user_prompt = f"""Generate a cold email application based on the following details:

---
### TARGET JOB DETAILS:
- Job Title: {job_title}
- Company: {company}
- Location: {location}
- Subject Code / Hint: {subject_hint}
- Job Description:
\"\"\"
{description[:4000]}
\"\"\"

---
### CANDIDATE DETAILS:
- Full Name: {candidate_name}
- Email: {candidate_email}
- Phone: {candidate_phone}

---
### CANDIDATE RESUME TEXT:
\"\"\"
{cv_text[:6000] if cv_text else "Technical background in software development, data science, and machine learning."}
\"\"\"

---
### OUTPUT FORMAT:
Return a valid JSON object matching the EmailDraftSchema schema.
"""

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
                    system_instruction=system_instruction,
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
        logger.warning(f"All Gemini models failed ({last_error}). Using heuristic draft.")
        result = generate_fallback_draft(
            job_title, company, subject_hint, candidate_name, cv_path, personal_signature
        )
        result["recipient_email"] = recipient_email
        result["job_id"] = job_id
        return result

    raw_ai_body = parsed_draft.get("body", "").strip()
    salutation = parsed_draft.get("salutation", "").strip()
    if salutation and not raw_ai_body.startswith(salutation) and not raw_ai_body.lower().startswith("dear"):
        raw_ai_body = f"{salutation}\n\n{raw_ai_body}"

    # Append the user's saved 'personal' signature cleanly at the end without duplicate sign-offs
    full_body = append_signature_safely(raw_ai_body, personal_signature, candidate_name)

    return {
        "status": "success",
        "engine": "gemini",
        "job_id": job_id,
        "recipient_email": recipient_email,
        "subject": parsed_draft.get("subject", f"Application for {job_title} - {candidate_name}"),
        "salutation": parsed_draft.get("salutation", f"Dear Hiring Team at {company},"),
        "body": full_body,
        "raw_ai_body": raw_ai_body,
        "key_highlights_used": parsed_draft.get("key_highlights_used", []),
        "attached_cv": {
            "path": cv_path,
            "filename": os.path.basename(cv_path) if cv_path else None,
            "size_kb": round(os.path.getsize(cv_path) / 1024, 1) if cv_path and os.path.exists(cv_path) else 0,
            "exists": os.path.exists(cv_path) if cv_path else False
        },
        "personal_signature": personal_signature,
        "has_personal_signature": bool(personal_signature and personal_signature.strip())
    }
