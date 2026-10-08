import os
import sys
import time
import json
import logging
import threading
import sqlite3
from typing import Dict, Any, Optional, List

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, '.env'))

from core.database import DB_PATH
from core.applicant_profile import load_profile, get_resume_for_role, resolve_contextual_screening
from appliers.screening_resolver import ScreeningResolver

logger = logging.getLogger(__name__)

# Active session tracking
class EasyApplySession:
    def __init__(self, job_id: str, job_url: str, title: str, company: str, site: str, cv_path: Optional[str]):
        self.job_id = job_id
        self.job_url = job_url
        self.title = title
        self.company = company
        self.site = site
        self.cv_path = cv_path
        self.cv_filename = os.path.basename(cv_path) if cv_path else None
        self.status = "idle"  # idle, launching, navigating, modal_opened, prefilling, paused_for_review, completed, error
        self.current_step = "Initialized"
        self.logs: List[str] = []
        self.error_message: Optional[str] = None
        self.created_at = time.time()
        self.browser_context = None

    def log(self, message: str):
        entry = f"[{time.strftime('%H:%M:%S')}] {message}"
        self.logs.append(entry)
        logger.info(f"[EasyApply:{self.job_id}] {message}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "title": self.title,
            "company": self.company,
            "site": self.site,
            "job_url": self.job_url,
            "cv_filename": self.cv_filename,
            "cv_path": self.cv_path,
            "status": self.status,
            "current_step": self.current_step,
            "logs": self.logs[-15:],  # Last 15 log entries
            "error_message": self.error_message
        }


ACTIVE_SESSIONS: Dict[str, EasyApplySession] = {}
SESSIONS_LOCK = threading.Lock()


def get_session(job_id: str) -> Optional[EasyApplySession]:
    with SESSIONS_LOCK:
        return ACTIVE_SESSIONS.get(job_id)


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


def prepare_easy_apply(job_id: str) -> Dict[str, Any]:
    """
    Pre-evaluates candidate details, matched role CV, and screening answers
    for the dashboard Easy Apply Co-Pilot preview modal.
    """
    job = get_job_by_id(job_id)
    if not job:
        return {"status": "error", "message": f"Job not found: {job_id}"}

    job_title = job.get("title", "")
    company = job.get("company", "")
    location = job.get("location", "")
    site = job.get("site", "")
    job_url = job.get("job_url", "")

    payload = job.get("apply_payload", {})
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {}

    target_url = payload.get("portal_url") or payload.get("job_url") or job_url

    profile = load_profile()
    personal = profile.get("personal_info", {})
    screening = profile.get("smart_screening", {})
    contextual = resolve_contextual_screening(location)

    cv_path = get_resume_for_role(job_title)

    return {
        "status": "success",
        "job_id": job_id,
        "title": job_title,
        "company": company,
        "location": location,
        "site": site,
        "job_url": target_url,
        "attached_cv": {
            "path": cv_path,
            "filename": os.path.basename(cv_path) if cv_path else None,
            "exists": os.path.exists(cv_path) if cv_path else False
        },
        "contact_preview": {
            "full_name": personal.get("full_name", "Mohamed Hussein"),
            "email": personal.get("email", "mhmd7syn.contact@gmail.com"),
            "phone": personal.get("phone", "+201012345678"),
            "city": personal.get("city", "Cairo"),
            "country": personal.get("country", "Egypt")
        },
        "screening_preview": {
            "requires_sponsorship": contextual.get("requires_visa_sponsorship", False),
            "willing_to_relocate": contextual.get("willing_to_relocate", True),
            "driving_license": screening.get("driving_license", False),
            "notice_period_days": screening.get("notice_period_days", 30),
            "expected_salary_egp": screening.get("expected_salary_egp", 35000),
            "expected_salary_usd": screening.get("expected_salary_usd", 1500)
        }
    }


def launch_easy_apply_session(job_id: str, headed: bool = True) -> Dict[str, Any]:
    """
    Spawns the assisted Playwright session in a background thread.
    Returns session metadata immediately so the UI can start polling.
    """
    job = get_job_by_id(job_id)
    if not job:
        return {"status": "error", "message": f"Job not found: {job_id}"}

    job_title = job.get("title", "")
    company = job.get("company", "")
    site = job.get("site", "")
    job_url = job.get("job_url", "")
    payload = job.get("apply_payload", {})
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {}
    target_url = payload.get("portal_url") or payload.get("job_url") or job_url

    cv_path = get_resume_for_role(job_title)

    session = EasyApplySession(
        job_id=job_id,
        job_url=target_url,
        title=job_title,
        company=company,
        site=site,
        cv_path=cv_path
    )

    with SESSIONS_LOCK:
        ACTIVE_SESSIONS[job_id] = session

    thread = threading.Thread(target=_run_assisted_session_thread, args=(session, headed), daemon=True)
    thread.start()

    return {
        "status": "success",
        "message": "Assisted Easy Apply session started.",
        "session": session.to_dict()
    }


def _run_assisted_session_thread(session: EasyApplySession, headed: bool = True):
    """
    Core assisted browser execution loop:
    1. Launches headed Chrome with persistent profile.
    2. Navigates to job listing.
    3. Finds and triggers Easy Apply modal.
    4. Pre-fills contact details, uploads CV, and answers screening questions.
    5. PAUSES before the final Submit button for the user to review and click!
    """
    from playwright.sync_api import sync_playwright

    session.status = "launching"
    session.current_step = "Launching Chrome browser..."
    session.log("Starting assisted headed Chrome session...")

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
                # If profile is locked by another running browser, fallback to fresh directory
                session.log(f"Profile lock detected ({e}). Using temporary profile session...")
                import tempfile
                temp_profile = tempfile.mkdtemp(prefix="playwright_wa_")
                launch_kwargs["user_data_dir"] = temp_profile
                context = p.chromium.launch_persistent_context(**launch_kwargs)

            session.browser_context = context
            page = context.pages[0] if context.pages else context.new_page()

            # 1. Navigate to target job URL
            session.status = "navigating"
            session.current_step = f"Navigating to {session.site.capitalize()} job listing..."
            session.log(f"Navigating to job listing: {session.job_url}")

            try:
                page.goto(session.job_url, timeout=35000, wait_until="domcontentloaded")
            except Exception as nav_err:
                session.log(f"Navigation note: {nav_err}")

            time.sleep(2.5)

            # 2. Locate and Click Easy Apply Button
            session.status = "opening_modal"
            session.current_step = "Locating Easy Apply button..."
            session.log("Scanning page for Easy Apply button...")

            apply_selectors = [
                # LinkedIn selectors
                "button.jobs-apply-button",
                "button:has-text('Easy Apply')",
                "button[data-control-name='jobdetails_topcard_inapply']",
                # Glassdoor selectors
                "button[data-test='easy-apply-button']",
                "button[data-test='apply-now-button']",
                "button:has-text('Apply on Employer')",
                "button.easyApply",
                # Indeed selectors
                "button.ia-IndeedApplyButton",
                "button:has-text('Apply now')",
                # Generic fallback
                "button:has-text('Apply')"
            ]

            apply_btn = None
            for sel in apply_selectors:
                try:
                    btn = page.query_selector(sel)
                    if btn and btn.is_visible():
                        btn_text = btn.inner_text().strip()
                        session.log(f"Found button matching '{sel}': '{btn_text}'")
                        apply_btn = btn
                        break
                except Exception:
                    continue

            if apply_btn:
                try:
                    apply_btn.click()
                    session.log("Clicked Easy Apply button. Waiting for modal...")
                    time.sleep(2.5)
                except Exception as click_err:
                    session.log(f"Could not click apply button: {click_err}")
            else:
                session.log("Notice: No distinct Easy Apply button clicked automatically. Inspecting current page/modal...")

            session.status = "prefilling"
            session.current_step = "Pre-filling application fields..."
            session.log("Starting multi-step form pre-filling loop...")

            # 3. Step Loop (Max 8 steps to prevent infinite loop)
            step_count = 0
            while step_count < 8:
                step_count += 1
                session.log(f"Processing application step #{step_count}...")
                time.sleep(1.2)

                # A. Handle File Upload (Resume / CV)
                file_inputs = page.query_selector_all("input[type='file']")
                for fin in file_inputs:
                    try:
                        if session.cv_path and os.path.exists(session.cv_path):
                            fin.set_input_files(session.cv_path)
                            session.log(f"✓ Uploaded matched role CV: {session.cv_filename}")
                            time.sleep(1.0)
                    except Exception as upload_err:
                        session.log(f"CV upload note: {upload_err}")

                # B. Handle Text, Email, Phone, Number Inputs
                text_inputs = page.query_selector_all("input:not([type='hidden']):not([type='file']):not([type='radio']):not([type='checkbox']):not([type='submit'])")
                for inp in text_inputs:
                    try:
                        if not inp.is_visible():
                            continue
                        current_val = inp.input_value()
                        if current_val and len(current_val.strip()) > 0:
                            continue  # Already filled

                        # Find identifying label or placeholder
                        inp_id = inp.get_attribute("id") or ""
                        inp_name = inp.get_attribute("name") or ""
                        inp_type = inp.get_attribute("type") or "text"
                        placeholder = inp.get_attribute("placeholder") or ""
                        aria_label = inp.get_attribute("aria-label") or ""

                        # Search for adjacent label
                        label_text = aria_label or placeholder
                        if inp_id and not label_text:
                            lbl = page.query_selector(f"label[for='{inp_id}']")
                            if lbl:
                                label_text = lbl.inner_text().strip()

                        if not label_text:
                            label_text = f"{inp_name} {inp_id}"

                        resolved_val = resolver.resolve_field_value(label_text, field_type=inp_type)
                        if resolved_val is not None and str(resolved_val).strip():
                            inp.fill(str(resolved_val))
                            session.log(f"Filled '{label_text[:30]}': {str(resolved_val)[:30]}")
                    except Exception:
                        continue

                # C. Handle Radio Buttons & Checkboxes
                radio_groups = page.query_selector_all("input[type='radio']")
                # Process radios by finding matching labels
                for r in radio_groups:
                    try:
                        if not r.is_visible():
                            continue
                        r_id = r.get_attribute("id") or ""
                        r_val = (r.get_attribute("value") or "").lower()
                        lbl = page.query_selector(f"label[for='{r_id}']") if r_id else None
                        lbl_text = lbl.inner_text().strip() if lbl else r_val

                        # If Yes/No question, select Yes by default for authorization/relocation
                        if lbl_text.lower() in ("yes", "نعم") and not r.is_checked():
                            r.click()
                            session.log(f"Selected radio: {lbl_text}")
                    except Exception:
                        continue

                # D. Check for Advance or Submit Buttons
                # Look for buttons in the modal
                advance_buttons = page.query_selector_all("button")
                found_next = False
                found_submit = False

                for btn in advance_buttons:
                    try:
                        if not btn.is_visible():
                            continue
                        txt = btn.inner_text().strip().lower()

                        # FINAL STEP CHECK: Submit / Submit application / Apply
                        if any(txt.startswith(k) for k in ["submit application", "submit", "apply now"]):
                            session.log(f"🛑 Reached final submission button: '{btn.inner_text().strip()}'")
                            found_submit = True
                            break

                        # Review button (some platforms have 'Review' before Submit)
                        if "review" in txt:
                            session.log("Clicking 'Review' to reach final submission page...")
                            btn.click()
                            time.sleep(1.5)
                            found_next = True
                            break

                        # Next / Continue button
                        if any(txt.startswith(k) for k in ["next", "continue", "save and continue"]):
                            session.log(f"Advancing: Clicked '{btn.inner_text().strip()}'")
                            btn.click()
                            time.sleep(1.5)
                            found_next = True
                            break
                    except Exception:
                        continue

                if found_submit:
                    # STRICT PHASE 1 RULE: STOP BEFORE SUBMIT!
                    session.status = "paused_for_review"
                    session.current_step = "Paused at final Review step! Ready for your click."
                    session.log("==================================================")
                    session.log("⏸ CO-PILOT PAUSE: Form pre-filled & CV attached!")
                    session.log("👉 Please review in the open Chrome browser and click Submit.")
                    session.log("==================================================")
                    return

                if not found_next:
                    # No next button found, might be a single-page modal or reached end
                    session.status = "paused_for_review"
                    session.current_step = "Form pre-filled. Please inspect and proceed."
                    session.log("Form ready. Please inspect the open browser window.")
                    return

            # If reached max steps
            session.status = "paused_for_review"
            session.current_step = "Paused for manual review."
            session.log("Reached review threshold. Please check the open Chrome window.")

    except Exception as e:
        session.status = "error"
        session.error_message = str(e)
        session.log(f"Error in assisted Easy Apply session: {e}")
