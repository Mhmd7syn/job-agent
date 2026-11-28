import os
import json
import re
import logging
import time
import urllib.parse
from datetime import datetime
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
from core.job_utils import normalize_phone_number

logger = logging.getLogger(__name__)

# Gemini client initialization
from core.gemini_client import get_gemini_client, generate_content_resilient

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None

client = get_gemini_client()


class WhatsAppPitchSchema(BaseModel):
    greeting: str = Field(
        default="",
        description="Polite personalized greeting to recruiter or hiring team (e.g. 'Hello Eraasoft Hiring Team,')."
    )
    introduction: str = Field(
        default="",
        description="Direct 1-line opener stating you're reaching out regarding the specific role."
    )
    key_highlights_used: list[str] = Field(
        default=[],
        description="2-3 brief bullet highlights of real skills or projects from the candidate's CV."
    )
    closing_and_attachment: str = Field(
        default="",
        description="Call to action explicitly noting that the CV is attached as a PDF, with a polite close."
    )
    signature: str = Field(
        default="",
        description="Sign-off with candidate's full name, email, phone, and LinkedIn profile."
    )
    pitch: str = Field(
        description="The complete structured outreach message strictly in professional English with double line breaks (\\n\\n) between paragraphs."
    )


def format_whatsapp_pitch(
    raw_pitch: str,
    candidate_name: str = "",
    cv_filename: Optional[str] = None,
    candidate_phone: str = "",
    candidate_email: str = "",
    linkedin_url: str = "",
) -> str:
    """
    Enforces clean, structured multi-paragraph formatting for WhatsApp messages:
    1. Greeting (e.g. 'Hello Eraasoft Hiring Team,')
    2. Short Introduction (e.g. "I'm reaching out regarding the role...")
    3. 2-3 Bullet Achievements (each starting with '• ')
    4. Call to Action + Explicit CV attachment mention
    5. Professional Sign-off & Contact signature
    
    Guarantees double line breaks (\\n\\n) separate distinct logical paragraphs,
    repairing single-block or collapsed text from LLMs.
    """
    text = (raw_pitch or "").replace("\r\n", "\n").strip()
    if not text:
        return ""

    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]

    # If the text is collapsed into a single or 2 lines without paragraph breaks
    if len(paragraphs) <= 2 and len(text.splitlines()) <= 2:
        greeting = ""
        sign_off = ""
        body = text

        gm = re.match(r'^(Dear [^,\n]+|Hello [^,\n]+|Hi [^,\n]+|Greetings [^,\n]+)[,:]?\s*', body, re.IGNORECASE)
        if gm:
            greeting = gm.group(1).strip()
            if not greeting.endswith(","):
                greeting += ","
            body = body[gm.end():].strip()

        sm = re.search(r'\s*(Best regards|Warm regards|Regards|Sincerely|Thank you|Thanks)[,:\s]+(.*)$', body, re.IGNORECASE | re.DOTALL)
        if sm:
            sign_off_phrase = sm.group(1).strip()
            sign_off_rest = sm.group(2).strip()
            sign_off = f"{sign_off_phrase},\n{sign_off_rest}" if sign_off_rest else f"{sign_off_phrase},\n{candidate_name}"
            body = body[:sm.start()].strip()
        elif candidate_name:
            contact_line = " | ".join(c for c in [candidate_phone, candidate_email, linkedin_url] if c)
            sign_off = f"Best regards,\n{candidate_name}" + (f"\n{contact_line}" if contact_line else "")

        bullet_items = []
        raw_bullets = re.findall(r'(?:^|\n|[.!?]\s*)([•\-\*]\s*[^•\-\*\n]+)', body)
        if raw_bullets:
            for b in raw_bullets:
                clean_b = b.lstrip("•-* ").strip()
                if clean_b:
                    bullet_items.append(clean_b)
            non_bullet = re.sub(r'[•\-\*]\s*[^•\-\*\n]+', ' ', body)
            sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', non_bullet) if s.strip()]
        else:
            sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', body) if s.strip()]

        if not bullet_items and len(sentences) >= 3:
            intro_sentence = sentences[0]
            closing_candidates = [s for s in sentences[1:] if any(k in s.lower() for k in ["attach", "resume", "cv", "chat", "connect", "forward"])]
            if closing_candidates:
                closing_sentence = " ".join(closing_candidates)
                mid_sentences = [s for s in sentences[1:] if s not in closing_candidates]
            else:
                closing_sentence = sentences[-1]
                mid_sentences = sentences[1:-1]
            bullet_items = mid_sentences
        elif not bullet_items:
            intro_sentence = sentences[0] if sentences else ""
            closing_sentence = " ".join(sentences[1:]) if len(sentences) > 1 else ""
        else:
            intro_sentence = sentences[0] if sentences else ""
            closing_sentence = " ".join(sentences[1:]) if len(sentences) > 1 else ""

        if not any(k in (closing_sentence + " " + intro_sentence).lower() for k in ["attach", "resume", "cv"]):
            cv_note = f"I've attached my resume ({cv_filename or 'PDF'}) for your review."
            closing_sentence = f"{closing_sentence} {cv_note}".strip() if closing_sentence else cv_note

        parts = []
        if greeting:
            parts.append(greeting)
        if intro_sentence:
            parts.append(intro_sentence)
        if bullet_items:
            bullets_str = "\n".join(f"• {b.lstrip('•-* ').strip()}" for b in bullet_items)
            parts.append(bullets_str)
        if closing_sentence:
            parts.append(closing_sentence)
        if sign_off:
            parts.append(sign_off)

        return "\n\n".join(parts)

    cleaned_paras = []
    has_attachment_mention = False

    for idx, p in enumerate(paragraphs):
        lines = [line.strip() for line in p.splitlines() if line.strip()]
        if not lines:
            continue
        if any(line.startswith(("•", "-", "*")) for line in lines):
            reformatted_bullets = []
            for line in lines:
                reformatted_bullets.append(f"• {line.lstrip('•-* ').strip()}")
            cleaned_paras.append("\n".join(reformatted_bullets))
        else:
            cleaned_paras.append("\n".join(lines))

        if any(k in p.lower() for k in ["attach", "resume", "cv"]):
            has_attachment_mention = True

    if not has_attachment_mention and len(cleaned_paras) >= 2:
        cv_note = f"I have attached my resume ({cv_filename or 'PDF'}) for your review."
        cleaned_paras.insert(-1, cv_note)

    return "\n\n".join(cleaned_paras)


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

    raw_fallback = (
        f"Hello Hiring Team at {comp_display},\n\n"
        f"I'm reaching out regarding the {job_title} role.\n\n"
        "• Relevant hands-on technical experience matching the core requirements\n"
        "• Proven track record delivering software and data solutions\n\n"
        "I have attached my resume (PDF) for your review. Looking forward to discussing how my experience can benefit your team.\n\n"
        f"Best regards,\n{candidate_name}"
    )

    contact_bits = [c for c in [candidate_phone, candidate_email, linkedin_url] if c]
    if contact_bits:
        raw_fallback += "\n" + " | ".join(contact_bits)

    cv_filename = os.path.basename(cv_path) if cv_path else "Resume.pdf"
    pitch_text = format_whatsapp_pitch(
        raw_fallback,
        candidate_name=candidate_name,
        cv_filename=cv_filename,
        candidate_phone=candidate_phone,
        candidate_email=candidate_email,
        linkedin_url=linkedin_url
    )

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
    job_data: Optional[Dict[str, Any]] = None,
    force_regenerate: bool = False,
    user_instructions: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generates a tailored, high-converting recruiter WhatsApp outreach pitch strictly in English.
    Extracts candidate profile context and matched role CV text from configuration.
    If a pitch was already generated and saved for this job, returns it without regenerating unless force_regenerate is True.
    """
    if not job_data and job_id:
        job_data = get_job_by_id(job_id)

    if not job_data:
        return {"status": "error", "message": f"Job not found for ID: {job_id}"}

    target_job_id = job_id or job_data.get("job_id")
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

    from core.apply_classifier import get_channel_payload
    wa_payload = get_channel_payload(apply_payload, "whatsapp")
    phone = wa_payload.get("phone") or apply_payload.get("phone", "")
    whatsapp_url = wa_payload.get("whatsapp_url") or apply_payload.get("whatsapp_url", "")
    normalized_phone = normalize_phone_number(phone)

    # Locate role-specific resume PDF
    cv_path = get_resume_for_role(job_title)

    # Check if a WhatsApp pitch was already generated and saved to this job
    saved_whatsapp = apply_payload.get("generated_whatsapp")
    if not force_regenerate and not user_instructions and saved_whatsapp and isinstance(saved_whatsapp, dict) and saved_whatsapp.get("pitch"):
        logger.info(f"Using saved WhatsApp pitch for job {target_job_id}")
        pitch_text = saved_whatsapp.get("pitch", "")
        return {
            "status": "success",
            "engine": saved_whatsapp.get("engine", "saved"),
            "pitch": pitch_text,
            "key_highlights_used": saved_whatsapp.get("key_highlights_used", []),
            "phone": saved_whatsapp.get("phone") or normalized_phone,
            "whatsapp_url": saved_whatsapp.get("whatsapp_url") or whatsapp_url or (f"https://wa.me/{normalized_phone}" if normalized_phone else ""),
            "wa_me_url": build_wa_me_url(normalized_phone, pitch_text),
            "web_url": build_whatsapp_web_url(normalized_phone, pitch_text),
            "is_saved": True,
            "generated_at": saved_whatsapp.get("generated_at"),
            "attached_cv": {
                "path": cv_path,
                "filename": os.path.basename(cv_path) if cv_path else None,
                "size_kb": round(os.path.getsize(cv_path) / 1024, 1) if cv_path and os.path.exists(cv_path) else 0,
                "exists": os.path.exists(cv_path) if cv_path else False
            },
            "job_id": target_job_id
        }

    # Load candidate profile
    profile = load_profile()
    personal_info = profile.get("personal_info", {})
    candidate_name = personal_info.get("full_name", "").strip()
    candidate_email = personal_info.get("email", "").strip()
    candidate_phone = personal_info.get("phone", "").strip()
    linkedin_url = personal_info.get("linkedin_url", "").strip()

    cv_text = ""
    if cv_path and os.path.exists(cv_path):
        try:
            cv_text = extract_text_from_file(cv_path)
        except Exception as e:
            logger.warning(f"Could not extract CV text from {cv_path}: {e}")

    # If no Gemini client, do not apply now; postpone to next run
    if not client:
        err_msg = "Gemini AI client is not initialized or API key is missing."
        logger.warning(f"Postponing WhatsApp pitch for '{job_title}' at '{company}': {err_msg}")
        return {
            "status": "error",
            "reason": "ai_unavailable",
            "message": f"AI unavailable ({err_msg}). Postponed to next run.",
            "job_id": job_id,
            "phone": normalized_phone
        }

    system_instruction = (
        "You are drafting a direct, natural WhatsApp outreach message to a recruiter or hiring manager.\n"
        "Tone: Friendly, conversational, professional—sounds like a competent person sending a quick mobile message, not an AI template.\n"
        "Length: 50–80 words maximum.\n\n"
        "CRITICAL RULES:\n"
        "1. STRICTLY ENGLISH LANGUAGE:\n"
        "   - Write in clear, natural English, even if the job description is in another language.\n"
        "2. NATURAL CONVERSATIONAL TONE:\n"
        "   - Use contractions naturally (I'm, I've).\n"
        "   - Use plain, active verbs (built, worked with) rather than corporate buzzwords (spearheaded, leveraged, orchestrated).\n"
        "   - BANNED IDIOMS & CLICHÉS: Never use colloquial idioms or slang. Never use AI cliches like 'I hope this finds you well', 'testament', 'delve', 'plethora', 'synergy', or 'esteemed'.\n"
        "3. MESSAGE STRUCTURE & PARAGRAPH FORMATTING (MANDATORY):\n"
        "   - Format the message into distinct paragraphs separated by double line breaks (\\n\\n):\n"
        "     Paragraph 1: Polite greeting (e.g., 'Hello {company} Hiring Team,' or 'Dear Hiring Team,')\n"
        "     Paragraph 2: Direct opener stating you're reaching out regarding the {job_title} role.\n"
        "     Paragraph 3: 2-3 brief bullet achievements (each on its own line starting with '• ') matching candidate's CV.\n"
        "     Paragraph 4: Call to action explicitly noting the CV/resume PDF is attached, with a low-friction close ('Happy to chat if my background looks like a fit.').\n"
        "     Paragraph 5: Sign off with candidate full name, email, phone, and LinkedIn profile.\n"
        "   - DO NOT collapse paragraphs into an unbroken text block.\n"
        "4. STRICT TRUTHFULNESS: Only mention real technologies and experiences from the CV. Never hallucinate.\n"
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

    writing_style = profile.get("writing_style", {})
    tone = writing_style.get("tone", "").strip()
    sample_writing = writing_style.get("sample_writing", "").strip()
    if tone:
        user_prompt += f"\n\nPREFERRED TONE:\n{tone}"
    if sample_writing:
        user_prompt += (
            f"\n\nCANDIDATE AUTHENTIC WRITING STYLE SAMPLE:\n"
            f'"""\n{sample_writing}\n"""\n'
            f"Please reflect the natural cadence, phrasing style, and authentic voice shown in this sample."
        )

    if user_instructions and user_instructions.strip():
        user_prompt += (
            f"\n\nADDITIONAL USER INSTRUCTIONS/FOCUS:\n"
            f"{user_instructions.strip()}\n"
            f"Please adhere strictly to these instructions."
        )

    try:
        response, model_used = generate_content_resilient(
            client=client,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=WhatsAppPitchSchema,
                temperature=0.2,
            ) if types else None,
            preferred_model="gemini-flash-lite-latest",
        )
        parsed = json.loads(response.text)
        raw_pitch = parsed.get("pitch", "").strip()
        highlights = parsed.get("key_highlights_used", [])

        # If subfields were generated, assemble fallback if raw_pitch collapsed
        greeting_sub = parsed.get("greeting", "").strip()
        intro_sub = parsed.get("introduction", "").strip()
        closing_sub = parsed.get("closing_and_attachment", "").strip()
        sig_sub = parsed.get("signature", "").strip()

        if (not raw_pitch or len(raw_pitch.split("\n\n")) < 3) and greeting_sub and intro_sub and closing_sub:
            bullets_text = "\n".join(f"• {h.lstrip('•-* ').strip()}" for h in highlights if h.strip())
            candidate_sig = sig_sub or f"Best regards,\n{candidate_name}"
            raw_pitch = f"{greeting_sub}\n\n{intro_sub}\n\n{bullets_text}\n\n{closing_sub}\n\n{candidate_sig}"

        cv_filename = os.path.basename(cv_path) if cv_path else "Resume.pdf"
        pitch_text = format_whatsapp_pitch(
            raw_pitch,
            candidate_name=candidate_name,
            cv_filename=cv_filename,
            candidate_phone=candidate_phone,
            candidate_email=candidate_email,
            linkedin_url=linkedin_url
        )

        now_iso = datetime.now().isoformat()
        if target_job_id:
            from core.database import save_job_generated_content
            save_job_generated_content(
                job_id=target_job_id,
                generated_whatsapp={
                    "pitch": pitch_text,
                    "key_highlights_used": highlights,
                    "phone": normalized_phone,
                    "whatsapp_url": whatsapp_url or (f"https://wa.me/{normalized_phone}" if normalized_phone else ""),
                    "engine": f"gemini ({model_used})",
                    "generated_at": now_iso
                }
            )

        return {
            "status": "success",
            "engine": f"gemini ({model_used})",
            "pitch": pitch_text,
            "key_highlights_used": highlights,
            "phone": normalized_phone,
            "whatsapp_url": whatsapp_url or (f"https://wa.me/{normalized_phone}" if normalized_phone else ""),
            "wa_me_url": build_wa_me_url(normalized_phone, pitch_text),
            "web_url": build_whatsapp_web_url(normalized_phone, pitch_text),
            "is_saved": False,
            "generated_at": now_iso,
            "attached_cv": {
                "path": cv_path,
                "filename": os.path.basename(cv_path) if cv_path else None,
                "size_kb": round(os.path.getsize(cv_path) / 1024, 1) if cv_path and os.path.exists(cv_path) else 0,
                "exists": os.path.exists(cv_path) if cv_path else False
            },
            "job_id": target_job_id
        }
    except Exception as e:
        err_msg = f"Gemini AI generation failed: {e}"
        logger.warning(f"Postponing WhatsApp application for '{job_title}' at '{company}': {err_msg}")
        return {
            "status": "error",
            "reason": "ai_unavailable",
            "message": f"AI unavailable ({err_msg}). Postponed to next run.",
            "job_id": job_id,
            "phone": normalized_phone
        }
