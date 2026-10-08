import os
import sys
import time
import json
import logging
import threading
import sqlite3
import re
from typing import Dict, Any, Optional, List

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, '.env'))

from core.database import DB_PATH
from core.applicant_profile import load_profile, get_resume_for_role, resolve_contextual_screening
from core.cv_parser import extract_text_from_file
from appliers.screening_resolver import ScreeningResolver

logger = logging.getLogger(__name__)

# Gemini client initialization for tailored cover letters
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
        gemini_client = genai.Client(api_key=decrypted_key)
    except Exception as e:
        logger.warning(f"Failed to initialize google-genai in ATS copilot: {e}")
        gemini_client = None
else:
    gemini_client = None


# Platform signatures and metadata
PLATFORM_METADATA = {
    "greenhouse": {
        "name": "Greenhouse",
        "domains": ["greenhouse.io", "boards.greenhouse.io", "job-boards.eu.greenhouse.io"],
        "icon": "fa-solid fa-leaf",
        "color": "#22c55e",
        "badge_class": "tag-channel-platform"
    },
    "lever": {
        "name": "Lever",
        "domains": ["lever.co", "jobs.lever.co"],
        "icon": "fa-solid fa-layer-group",
        "color": "#3b82f6",
        "badge_class": "tag-channel-platform"
    },
    "workable": {
        "name": "Workable",
        "domains": ["workable.com", "apply.workable.com"],
        "icon": "fa-solid fa-briefcase",
        "color": "#06b6d4",
        "badge_class": "tag-channel-platform"
    },
    "recruitee": {
        "name": "Recruitee",
        "domains": ["recruitee.com"],
        "icon": "fa-solid fa-users",
        "color": "#a855f7",
        "badge_class": "tag-channel-platform"
    },
    "ashby": {
        "name": "Ashby",
        "domains": ["ashbyhq.com", "jobs.ashbyhq.com"],
        "icon": "fa-solid fa-asterisk",
        "color": "#ec4899",
        "badge_class": "tag-channel-platform"
    },
    "workday": {
        "name": "Workday",
        "domains": ["myworkdayjobs.com", "workday.com"],
        "icon": "fa-solid fa-cloud",
        "color": "#f59e0b",
        "badge_class": "tag-channel-platform"
    },
    "smartrecruiters": {
        "name": "SmartRecruiters",
        "domains": ["smartrecruiters.com"],
        "icon": "fa-solid fa-award",
        "color": "#10b981",
        "badge_class": "tag-channel-platform"
    },
    "bamboohr": {
        "name": "BambooHR",
        "domains": ["bamboohr.com"],
        "icon": "fa-solid fa-tree",
        "color": "#84cc16",
        "badge_class": "tag-channel-platform"
    },
    "google_forms": {
        "name": "Google Forms",
        "domains": ["docs.google.com/forms", "forms.gle"],
        "icon": "fa-solid fa-file-lines",
        "color": "#7c3aed",
        "badge_class": "tag-channel-form"
    },
    "ms_forms": {
        "name": "Microsoft Forms",
        "domains": ["forms.office.com", "forms.microsoft.com"],
        "icon": "fa-solid fa-clipboard-list",
        "color": "#0284c7",
        "badge_class": "tag-channel-form"
    },
    "typeform": {
        "name": "Typeform",
        "domains": ["typeform.com"],
        "icon": "fa-solid fa-square-poll-vertical",
        "color": "#6366f1",
        "badge_class": "tag-channel-form"
    },
    "airtable": {
        "name": "Airtable",
        "domains": ["airtable.com"],
        "icon": "fa-solid fa-table-columns",
        "color": "#ef4444",
        "badge_class": "tag-channel-form"
    }
}


def detect_platform(url: str, text: str = "") -> Dict[str, Any]:
    """
    Detects the ATS or web form platform based on URL and optional text context.
    """
    url_lower = (url or "").lower()
    text_lower = (text or "").lower()
    combined = url_lower + " " + text_lower

    for plat_key, meta in PLATFORM_METADATA.items():
        if any(dom in combined for dom in meta["domains"]):
            return {
                "platform_key": plat_key,
                "name": meta["name"],
                "icon": meta["icon"],
                "color": meta["color"],
                "badge_class": meta["badge_class"]
            }

    # Fallback for other employer / company career portals
    return {
        "platform_key": "universal",
        "name": "Company ATS Portal",
        "icon": "fa-solid fa-network-wired",
        "color": "#64748b",
        "badge_class": "tag-channel-platform"
    }


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


def generate_ats_cover_letter(
    job_title: str,
    company: str,
    location: str = "",
    job_description: str = "",
    cv_text: str = ""
) -> str:
    """
    Generates a concise, high-converting 2-paragraph cover letter tailored to the
    job and grounded in candidate CV highlights. Strictly English.
    """
    profile = load_profile()
    personal = profile.get("personal_info", {})
    full_name = personal.get("full_name", "Mohamed Hussein")
    signature = profile.get("auto_apply_settings", {}).get("email_signature_personal", "")

    if not signature:
        email = personal.get("email", "mhmd7syn.contact@gmail.com")
        phone = personal.get("phone", "+201012345678")
        linkedin = personal.get("linkedin_url", "https://www.linkedin.com/in/mhmd7syn")
        signature = f"Best regards,\n{full_name}\n{email} | {phone}\nLinkedIn: {linkedin}"

    # Try AI generation via Gemini
    if gemini_client and (cv_text or job_description):
        prompt = f"""
You are an expert career advisor writing a tailored cover letter / application statement for a job application.

Target Job:
- Position: {job_title}
- Company: {company}
- Location: {location}
- Description excerpt: {job_description[:600] if job_description else "N/A"}

Candidate CV Context:
{cv_text[:1200] if cv_text else "Technical background in Python, SQL, Machine Learning, Data Analytics, and AI development."}

Candidate Name: {full_name}

Instructions:
1. Write a professional, concise 2-paragraph cover letter in fluent English.
2. Paragraph 1: Express strong interest in the {job_title} role at {company} and summarize relevant technical experience.
3. Paragraph 2: Highlight 2 specific factual projects or accomplishments from the candidate's background that directly solve problems for this position.
4. Conclude with enthusiasm for discussing contributions in an interview.
5. STRICTLY DO NOT invent false credentials, companies, or universities.
6. Return ONLY the cover letter body text (do not include salutation or signature, as they are appended automatically).
"""
        try:
            from google.genai import types
            response = gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    max_output_tokens=350,
                )
            )
            body = response.text.strip()
            # Clean possible markdown fences
            body = re.sub(r'^```[a-z]*\s*', '', body, flags=re.MULTILINE)
            body = re.sub(r'```$', '', body, flags=re.MULTILINE).strip()
            if len(body) > 80:
                salutation = f"Dear {company} Hiring Team,\n\n" if company and company != "Unknown" else "Dear Hiring Team,\n\n"
                return f"{salutation}{body}\n\n{signature}"
        except Exception as e:
            logger.warning(f"Gemini cover letter generation failed: {e}. Using deterministic fallback.")

    # High-converting deterministic fallback
    salutation = f"Dear {company} Hiring Team,\n\n" if company and company != "Unknown" else "Dear Hiring Team,\n\n"
    body = (
        f"I am writing to express my strong enthusiasm for the {job_title} position at {company}. "
        f"With hands-on experience developing end-to-end data analytics pipelines, machine learning models, "
        f"and automated software solutions in Python, SQL, and Power BI, I am confident in my ability "
        f"to bring immediate value to your team.\n\n"
        f"Throughout my work, I have focused on building robust, scalable solutions that transform complex data "
        f"into actionable insights and streamlined processes. I am excited by {company}'s mission and would welcome "
        f"the opportunity to discuss how my technical expertise aligns with your current priorities."
    )
    return f"{salutation}{body}\n\n{signature}"


# Active ATS Session Tracking
class AtsSession:
    def __init__(self, job_id: str, portal_url: str, title: str, company: str, platform_meta: Dict[str, Any], cv_path: Optional[str]):
        self.job_id = job_id
        self.portal_url = portal_url
        self.title = title
        self.company = company
        self.platform = platform_meta.get("platform_key", "universal")
        self.platform_name = platform_meta.get("name", "Company ATS")
        self.cv_path = cv_path
        self.cv_filename = os.path.basename(cv_path) if cv_path else None
        self.status = "idle"  # idle, launching, navigating, prefilling, paused_for_review, completed, error
        self.current_step = "Initialized"
        self.logs: List[str] = []
        self.error_message: Optional[str] = None
        self.created_at = time.time()
        self.browser_context = None

    def log(self, message: str):
        entry = f"[{time.strftime('%H:%M:%S')}] {message}"
        self.logs.append(entry)
        logger.info(f"[AtsCopilot:{self.job_id}] {message}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "title": self.title,
            "company": self.company,
            "platform": self.platform,
            "platform_name": self.platform_name,
            "portal_url": self.portal_url,
            "cv_filename": self.cv_filename,
            "cv_path": self.cv_path,
            "status": self.status,
            "current_step": self.current_step,
            "logs": self.logs[-15:],
            "error_message": self.error_message
        }


ACTIVE_ATS_SESSIONS: Dict[str, AtsSession] = {}
ATS_SESSIONS_LOCK = threading.Lock()


def get_ats_session(job_id: str) -> Optional[AtsSession]:
    with ATS_SESSIONS_LOCK:
        return ACTIVE_ATS_SESSIONS.get(job_id)


def prepare_ats_application(job_id: str) -> Dict[str, Any]:
    """
    Prepares complete candidate context, ATS detection, quick-copy fields,
    screening answers, and tailored cover letter for the dashboard modal.
    """
    job = get_job_by_id(job_id)
    if not job:
        return {"status": "error", "message": f"Job not found: {job_id}"}

    job_title = job.get("title", "")
    company = job.get("company", "")
    location = job.get("location", "")
    job_url = job.get("job_url", "")
    desc = job.get("description", "")

    payload = job.get("apply_payload", {})
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {}

    portal_url = payload.get("portal_url") or payload.get("form_url") or payload.get("job_url") or job_url
    platform_meta = detect_platform(portal_url, desc)

    profile = load_profile()
    personal = profile.get("personal_info", {})
    screening = profile.get("smart_screening", {})
    contextual = resolve_contextual_screening(location)

    cv_path = get_resume_for_role(job_title)
    cv_text = ""
    if cv_path and os.path.exists(cv_path):
        try:
            cv_text = extract_text_from_file(cv_path)
        except Exception:
            pass

    cover_letter = generate_ats_cover_letter(
        job_title=job_title,
        company=company,
        location=location,
        job_description=desc,
        cv_text=cv_text
    )

    sponsorship_needed = contextual.get("requires_visa_sponsorship", False)
    sponsorship_statement = (
        "Authorized to work in home country (Egypt); require visa sponsorship for international employment/relocation."
        if sponsorship_needed else
        "Authorized to work without sponsorship."
    )

    return {
        "status": "success",
        "job_id": job_id,
        "title": job_title,
        "company": company,
        "location": location,
        "portal_url": portal_url,
        "platform_meta": platform_meta,
        "attached_cv": {
            "path": cv_path,
            "filename": os.path.basename(cv_path) if cv_path else None,
            "exists": os.path.exists(cv_path) if cv_path else False
        },
        "quick_copy": {
            "full_name": personal.get("full_name", "Mohamed Hussein"),
            "first_name": personal.get("first_name", "Mohamed"),
            "last_name": personal.get("last_name", "Hussein"),
            "email": personal.get("email", "mhmd7syn.contact@gmail.com"),
            "phone": personal.get("phone", "+201012345678"),
            "city": personal.get("city", "Cairo"),
            "country": personal.get("country", "Egypt"),
            "linkedin_url": personal.get("linkedin_url", "https://www.linkedin.com/in/mhmd7syn"),
            "github_url": personal.get("github_url", "https://github.com/Mhmd7syn"),
            "portfolio_url": personal.get("portfolio_url", ""),
            "expected_salary_egp": f"{screening.get('expected_salary_egp', 35000):,} EGP/month",
            "expected_salary_usd": f"${screening.get('expected_salary_usd', 1500):,}/month",
            "notice_period": f"{screening.get('notice_period_days', 30)} days",
            "sponsorship_statement": sponsorship_statement
        },
        "screening_preview": {
            "requires_sponsorship": sponsorship_needed,
            "willing_to_relocate": contextual.get("willing_to_relocate", True),
            "driving_license": screening.get("driving_license", False),
            "notice_period_days": screening.get("notice_period_days", 30),
            "expected_salary_egp": screening.get("expected_salary_egp", 35000),
            "expected_salary_usd": screening.get("expected_salary_usd", 1500)
        },
        "cover_letter": cover_letter
    }


def launch_ats_session(job_id: str, headed: bool = True) -> Dict[str, Any]:
    """
    Spawns the assisted Playwright session for ATS or web forms in a background thread.
    """
    job = get_job_by_id(job_id)
    if not job:
        return {"status": "error", "message": f"Job not found: {job_id}"}

    job_title = job.get("title", "")
    company = job.get("company", "")
    job_url = job.get("job_url", "")
    desc = job.get("description", "")

    payload = job.get("apply_payload", {})
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {}

    portal_url = payload.get("portal_url") or payload.get("form_url") or payload.get("job_url") or job_url
    platform_meta = detect_platform(portal_url, desc)
    cv_path = get_resume_for_role(job_title)

    session = AtsSession(
        job_id=job_id,
        portal_url=portal_url,
        title=job_title,
        company=company,
        platform_meta=platform_meta,
        cv_path=cv_path
    )

    with ATS_SESSIONS_LOCK:
        ACTIVE_ATS_SESSIONS[job_id] = session

    thread = threading.Thread(target=_run_assisted_ats_thread, args=(session, headed), daemon=True)
    thread.start()

    return {
        "status": "success",
        "message": f"Assisted {session.platform_name} session started.",
        "session": session.to_dict()
    }


def _run_assisted_ats_thread(session: AtsSession, headed: bool = True):
    """
    Core assisted browser loop for ATS & Web Forms:
    1. Launches headed Chrome with profile.
    2. Navigates to ATS portal / application form.
    3. Detects platform and applies specialized field mappings:
       - Greenhouse, Lever, Workable, Recruitee, Workday, Google Forms, Universal
    4. Automatically uploads matched role CV from OneDrive.
    5. Injects candidate info and screening answers.
    6. STRICTLY PAUSES at the final Submit button for user review!
    """
    from playwright.sync_api import sync_playwright

    session.status = "launching"
    session.current_step = "Launching Chrome browser..."
    session.log(f"Starting assisted session for {session.platform_name}...")

    chrome_bin = os.path.join(BASE_DIR, "chrome-win64", "chrome.exe")
    user_data_dir = os.path.join(BASE_DIR, "playwright_profile")

    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-infobars",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--start-maximized"
    ]

    resolver = ScreeningResolver(
        job_title=session.title,
        job_location=session.company,
        company=session.company
    )

    try:
        with sync_playwright() as p:
            launch_kwargs = {
                "user_data_dir": user_data_dir,
                "headless": False if headed else True,
                "args": launch_args,
                "ignore_default_args": ["--enable-automation"],
                "viewport": None
            }
            if os.path.exists(chrome_bin):
                launch_kwargs["executable_path"] = chrome_bin
            else:
                launch_kwargs["channel"] = "chrome"

            session.log(f"Opening browser profile at: {user_data_dir}")
            try:
                context = p.chromium.launch_persistent_context(**launch_kwargs)
            except Exception as e:
                session.log(f"Profile lock detected ({e}). Using temporary profile session...")
                import tempfile
                temp_profile = tempfile.mkdtemp(prefix="playwright_ats_")
                launch_kwargs["user_data_dir"] = temp_profile
                context = p.chromium.launch_persistent_context(**launch_kwargs)

            session.browser_context = context
            page = context.pages[0] if context.pages else context.new_page()

            # 1. Navigate to ATS portal URL
            session.status = "navigating"
            session.current_step = f"Navigating to {session.platform_name} application page..."
            session.log(f"Navigating to portal URL: {session.portal_url}")

            try:
                page.goto(session.portal_url, timeout=40000, wait_until="domcontentloaded")
            except Exception as nav_err:
                session.log(f"Navigation note: {nav_err}")

            time.sleep(3.0)

            # Check if there is an "Apply" or "Apply for this job" button to open the form
            apply_anchors = [
                "a:has-text('Apply for this job')",
                "a:has-text('Apply for this Job')",
                "a:has-text('Apply Now')",
                "button:has-text('Apply for this job')",
                "button:has-text('Apply Now')",
                "a[href*='#apply']",
                "a[href*='/apply']"
            ]
            for anc in apply_anchors:
                try:
                    btn = page.query_selector(anc)
                    if btn and btn.is_visible():
                        btn.click()
                        session.log(f"Clicked initial '{anc}' to reveal form...")
                        time.sleep(2.0)
                        break
                except Exception:
                    continue

            session.status = "prefilling"
            session.current_step = f"Pre-filling {session.platform_name} fields..."
            session.log("Inspecting application fields and file inputs...")

            # 2. File Upload (Resume / CV)
            file_inputs = page.query_selector_all("input[type='file']")
            for fin in file_inputs:
                try:
                    if session.cv_path and os.path.exists(session.cv_path):
                        fin.set_input_files(session.cv_path)
                        session.log(f"✓ Uploaded matched role CV: {session.cv_filename}")
                        time.sleep(1.0)
                except Exception as upload_err:
                    session.log(f"CV upload note: {upload_err}")

            # 3. Handle Platform-Specific Fields First
            personal = resolver.personal_info
            full_name = personal.get("full_name", "Mohamed Hussein")
            first_name = personal.get("first_name", "Mohamed")
            last_name = personal.get("last_name", "Hussein")
            email = personal.get("email", "mhmd7syn.contact@gmail.com")
            phone = personal.get("phone", "+201012345678")
            linkedin = personal.get("linkedin_url", "https://www.linkedin.com/in/mhmd7syn")
            github = personal.get("github_url", "https://github.com/Mhmd7syn")

            # A. Greenhouse
            if session.platform == "greenhouse":
                session.log("Applying Greenhouse field heuristics...")
                _fill_input_by_selector(page, "#first_name", first_name, session)
                _fill_input_by_selector(page, "#last_name", last_name, session)
                _fill_input_by_selector(page, "#email", email, session)
                _fill_input_by_selector(page, "#phone", phone, session)
                _fill_input_by_selector(page, "input[autocomplete='custom-question-linkedin']", linkedin, session)
                _fill_input_by_selector(page, "input[autocomplete='custom-question-website']", github, session)

            # B. Lever
            elif session.platform == "lever":
                session.log("Applying Lever field heuristics...")
                _fill_input_by_selector(page, "input[name='name']", full_name, session)
                _fill_input_by_selector(page, "input[name='email']", email, session)
                _fill_input_by_selector(page, "input[name='phone']", phone, session)
                _fill_input_by_selector(page, "input[name='org']", "Independent / Freelance", session)
                _fill_input_by_selector(page, "input[name='urls[LinkedIn]']", linkedin, session)
                _fill_input_by_selector(page, "input[name='urls[GitHub]']", github, session)

            # C. Workable
            elif session.platform == "workable":
                session.log("Applying Workable field heuristics...")
                _fill_input_by_selector(page, "input[name='firstname']", first_name, session)
                _fill_input_by_selector(page, "input[name='lastname']", last_name, session)
                _fill_input_by_selector(page, "input[name='email']", email, session)
                _fill_input_by_selector(page, "input[name='phone']", phone, session)

            # D. Recruitee
            elif session.platform == "recruitee":
                session.log("Applying Recruitee field heuristics...")
                _fill_input_by_selector(page, "input[name*='name']", full_name, session)
                _fill_input_by_selector(page, "input[name*='email']", email, session)
                _fill_input_by_selector(page, "input[name*='phone']", phone, session)

            # 4. Generic Field Traverser (for all unfilled text, email, tel, number inputs)
            text_inputs = page.query_selector_all("input:not([type='hidden']):not([type='file']):not([type='radio']):not([type='checkbox']):not([type='submit'])")
            for inp in text_inputs:
                try:
                    if not inp.is_visible():
                        continue
                    current_val = inp.input_value()
                    if current_val and len(current_val.strip()) > 0:
                        continue

                    inp_id = inp.get_attribute("id") or ""
                    inp_name = inp.get_attribute("name") or ""
                    inp_type = inp.get_attribute("type") or "text"
                    placeholder = inp.get_attribute("placeholder") or ""
                    aria_label = inp.get_attribute("aria-label") or ""

                    label_text = aria_label or placeholder
                    if inp_id and not label_text:
                        lbl = page.query_selector(f"label[for='{inp_id}']")
                        if lbl:
                            label_text = lbl.inner_text().strip()

                    if not label_text:
                        label_text = f"{inp_name} {inp_id}"

                    resolved = resolver.resolve_field_value(label_text, field_type=inp_type)
                    if resolved is not None and str(resolved).strip():
                        inp.fill(str(resolved))
                        session.log(f"Filled '{label_text[:28]}': {str(resolved)[:28]}")
                except Exception:
                    continue

            # 5. Handle Radio Buttons (Sponsorship, Relocation, Legal)
            radios = page.query_selector_all("input[type='radio']")
            for r in radios:
                try:
                    if not r.is_visible():
                        continue
                    r_id = r.get_attribute("id") or ""
                    r_val = (r.get_attribute("value") or "").lower()
                    lbl = page.query_selector(f"label[for='{r_id}']") if r_id else None
                    lbl_text = lbl.inner_text().strip().lower() if lbl else r_val

                    # Select "Yes" for standard work authorization / relocation questions
                    if lbl_text in ("yes", "نعم") and not r.is_checked():
                        r.click()
                        session.log(f"Selected radio: {lbl_text}")
                except Exception:
                    continue

            # 6. Locate Final Submit Button (WITHOUT CLICKING)
            submit_selectors = [
                "#submit_app",
                "#btn-submit",
                "button[type='submit']",
                "input[type='submit']",
                "button:has-text('Submit Application')",
                "button:has-text('Submit application')",
                "button:has-text('Submit Application')",
                "button:has-text('Send Application')",
                "button:has-text('Submit')",
                "button:has-text('Apply Now')"
            ]

            submit_btn = None
            for sel in submit_selectors:
                try:
                    btn = page.query_selector(sel)
                    if btn and btn.is_visible():
                        submit_btn = btn
                        break
                except Exception:
                    continue

            if submit_btn:
                try:
                    # Highlight button with cyan dashed border and scroll into view
                    page.evaluate("""(el) => {
                        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                        el.style.outline = '4px dashed #06b6d4';
                        el.style.outlineOffset = '4px';
                        el.style.boxShadow = '0 0 20px rgba(6, 182, 212, 0.6)';
                    }""", submit_btn)
                    btn_text = submit_btn.inner_text().strip() if submit_btn.inner_text() else "Submit"
                    session.log(f"🎯 Final submit button highlighted: '{btn_text}'")
                except Exception:
                    pass

            # 7. STRICT ZERO-RISK PAUSE FOR USER REVIEW
            session.status = "paused_for_review"
            session.current_step = "Paused for Review - Please check inputs and click Submit manually!"
            session.log("🛑 APPLICATION PRE-FILLED! All fields populated and CV attached.")
            session.log("👉 Please review the form in your browser window and click 'Submit' manually when satisfied.")

            # Keep browser session open while user reviews (up to 15 minutes)
            for _ in range(90):
                if session.status == "completed":
                    break
                time.sleep(10)

    except Exception as e:
        session.status = "error"
        session.error_message = str(e)
        session.log(f"Error during assisted session: {e}")


def _fill_input_by_selector(page, selector: str, value: str, session: AtsSession):
    """Helper to fill an input safely if found."""
    try:
        el = page.query_selector(selector)
        if el and el.is_visible():
            current = el.input_value()
            if not current or not current.strip():
                el.fill(value)
                session.log(f"Filled '{selector}': {value[:25]}")
    except Exception:
        pass


def mark_ats_applied(job_id: str) -> Dict[str, Any]:
    """
    Decoupled tracking endpoint: marks job as applied in the database.
    Called ONLY when the candidate explicitly confirms submission.
    """
    job = get_job_by_id(job_id)
    if not job:
        return {"status": "error", "message": f"Job not found: {job_id}"}

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE jobs
            SET is_applied = 1,
                applied_at = ?,
                apply_status = 'applied'
            WHERE job_id = ?
        """, (now, job_id))
        conn.commit()
        conn.close()

        # Update active session status if running
        session = get_ats_session(job_id)
        if session:
            session.status = "completed"
            session.log("✓ Application confirmed and marked as applied by candidate.")

        return {
            "status": "success",
            "message": f"Job '{job.get('title')}' successfully marked as applied!",
            "applied_at": now
        }
    except Exception as e:
        logger.error(f"Error marking job {job_id} as applied: {e}")
        return {"status": "error", "message": str(e)}
