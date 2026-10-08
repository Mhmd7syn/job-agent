import re
import json
import logging
import urllib.parse
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

ARABIC_DIGITS_TRANS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

def normalize_arabic_digits(text: str) -> str:
    """Converts Eastern Arabic numerals (٠-٩) to Western standard numerals (0-9)."""
    if not text:
        return ""
    return text.translate(ARABIC_DIGITS_TRANS)

EMAIL_REGEX = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')

IGNORE_EMAIL_DOMAINS = {
    "linkedin.com", "indeed.com", "glassdoor.com", "wuzzuf.net", 
    "tanqeeb.com", "bayt.com", "example.com", "sentry.io"
}

IGNORE_EMAIL_PREFIXES = {
    "privacy", "support", "help", "noreply", "no-reply", "donotreply", 
    "info@linkedin", "contact@linkedin", "abuse", "security"
}

def clean_email(raw_email: str) -> str:
    """Strips surrounding brackets, quotes, trailing dots, and whitespace from emails."""
    return raw_email.strip().strip(".,;:()<>[]\"' \t\r\n").rstrip('.')

def is_valid_recruiter_email(email: str) -> bool:
    if not email or "@" not in email:
        return False
    email_clean = clean_email(email).lower()
    if "@" not in email_clean:
        return False
    prefix, domain = email_clean.split("@", 1)
    
    if "." not in domain or len(prefix) < 1 or len(domain) < 3:
        return False
        
    for ign_dom in IGNORE_EMAIL_DOMAINS:
        if domain == ign_dom or domain.endswith("." + ign_dom):
            return False
            
    for ign_pre in IGNORE_EMAIL_PREFIXES:
        if prefix == ign_pre or ign_pre in email_clean:
            return False
            
    return True

def extract_subject_hint(text: str) -> Optional[str]:
    patterns = [
        # Pattern 1: Please mention "Data Analyst" in the email subject line
        r'(?:mention(?:ing)?|write|put)\s+["\'“]([^"\'”\r\n]{3,60})["\'”]\s+(?:in|as)\s+(?:the\s+)?(?:email\s+)?subject',
        # Pattern 2: Quoted subject after subject trigger
        r'(?:subject\s+line|with\s+subject|subject|mentioning|titled)[\s:]+["\'“]([^"\'”\r\n]{3,60})["\'”]',
        # Pattern 3: Unquoted subject after trigger
        r'(?:subject\s+line|with\s+subject|subject|mentioning|titled)[\s:]+([A-Za-z0-9\s\-–—/]{3,50})(?:\.|\n|\r|$)',
        # Pattern 4: Fallback
        r'subject[\s:]+([^\n\r]{3,60})'
    ]
    invalid_hints = {"line", "the line", "subject line", "the subject", "subject", "email", "the email", "email subject"}
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            hint = m.group(1).strip().strip(".,:;\"' \t\r\n")
            if len(hint) >= 3 and hint.lower() not in invalid_hints:
                return hint
    return None

def normalize_phone_number(raw_phone: str) -> Optional[str]:
    """
    Normalizes Egyptian, Gulf, and international numbers into clean E.164 digits without leading +.
    e.g. '01012345678' -> '201012345678'
         '+20 11 2345 6789' -> '201123456789'
         '00966501234567' -> '966501234567'
    """
    digits = re.sub(r'\D', '', raw_phone)
    
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

    # General international number (10 to 14 digits)
    if 10 <= len(digits) <= 14:
        return digits
        
    return None

WHATSAPP_LINK_REGEX = re.compile(
    r'https?://(?:api\.whatsapp\.com/send\?(?:[^&]+&)*phone=(\d+)|(?:wa\.me|wa\.link)/(\d+)|chat\.whatsapp\.com/[A-Za-z0-9]+)',
    re.IGNORECASE
)

WHATSAPP_TRIGGERS = [
    "whatsapp", "واتساب", "واتس", "wa.me", "send cv", "ارسال السيرة", "إرسال السيرة",
    "تواصل واتس", "على الرقم", "عبر الواتساب", "cv to", "resume to"
]

EGYPT_PHONE_REGEX = re.compile(r'(?:(?:\+|00)?20[\s\-.]?|0)?1[0125](?:[\s\-.]?\d){8}\b')
GULF_PHONE_REGEX = re.compile(r'(?:(?:\+|00)?(?:966|971)[\s\-.]?|0)?5(?:[\s\-.]?\d){8}\b')

FORM_DOMAINS = [
    'forms.gle', 'docs.google.com/forms', 'forms.office.com', 'forms.microsoft.com',
    'typeform.com', 'airtable.com', 'jotform.com', 'tally.so'
]

ATS_PATTERNS = {
    "greenhouse": ["greenhouse.io", "boards.greenhouse.io", "job-boards.greenhouse.io"],
    "lever": ["lever.co", "jobs.lever.co"],
    "ashby": ["ashbyhq.com", "jobs.ashbyhq.com"],
    "workday": ["myworkdayjobs.com", "workday.com"],
    "smartrecruiters": ["smartrecruiters.com"],
    "bamboohr": ["bamboohr.com"],
    "taleo": ["taleo.net", "taleo.com"],
    "workable": ["workable.com", "apply.workable.com"],
    "jobvite": ["jobvite.com"],
    "breezy": ["breezy.hr"],
    "personio": ["personio.com", "personio.de"],
    "recruitee": ["recruitee.com"],
    "jazzhr": ["jazzhr.com"],
    "rippling": ["rippling-ats.com", "rippling.com"],
    "icims": ["icims.com"]
}

JOB_BOARD_DOMAINS = {
    "linkedin": "LinkedIn",
    "glassdoor": "Glassdoor",
    "indeed": "Indeed",
    "wuzzuf": "Wuzzuf",
    "bayt": "Bayt",
    "tanqeeb": "Tanqeeb"
}

def extract_form_url(text: str) -> Optional[str]:
    """Finds application form URLs (Google Forms, MS Forms, Typeform, Airtable, etc.)."""
    for domain in FORM_DOMAINS:
        if domain in text.lower():
            pattern = rf'https?://[^\s<>"\']*?{re.escape(domain)}[^\s<>"\']*'
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                return m.group(0).rstrip('.,;)]}>"')
            return domain
    return None

def classify_and_extract(job: Dict[str, Any]) -> Dict[str, Any]:
    """
    Analyzes a job record and returns:
      - apply_type: 'email', 'whatsapp', 'form', 'platform', 'easy_apply', 'social_post', 'job_board', or 'manual'
      - apply_payload: Dict with extracted and structured channel data
    """
    desc_raw = job.get("description") or ""
    url = (job.get("job_url") or "").strip()
    apply_url = (job.get("apply_url") or "").strip()
    site = (job.get("site") or "").lower()
    raw_ea = job.get("is_easy_apply")
    if raw_ea is not None:
        if isinstance(raw_ea, str):
            is_easy_apply_flag = raw_ea.lower() in ("1", "true", "yes")
        else:
            is_easy_apply_flag = bool(raw_ea)
    else:
        is_easy_apply_flag = None
    
    desc = normalize_arabic_digits(desc_raw)
    combined = (url + "\n" + apply_url + "\n" + desc)
    url_lower = url.lower()
    apply_url_lower = apply_url.lower()
    
    # 1. Check for Recruiter Email
    if "@" in desc:
        emails = EMAIL_REGEX.findall(desc)
        valid_emails = [clean_email(e) for e in emails if is_valid_recruiter_email(clean_email(e))]
        if valid_emails:
            recipient = valid_emails[0]
            subject_hint = extract_subject_hint(desc)
            return {
                "apply_type": "email",
                "apply_payload": {
                    "recipient_email": recipient,
                    "all_emails": valid_emails,
                    "subject_hint": subject_hint or f"Application for {job.get('title', 'Position')} - Mohamed Hussein"
                }
            }

    # 2. Check for Application Forms (Google Forms, Typeform, Office Forms, Airtable, etc.)
    form_in_url = extract_form_url(url) or (extract_form_url(apply_url) if apply_url else None)
    form_in_desc = extract_form_url(desc)
    form_url = form_in_url or form_in_desc
    if form_url:
        return {
            "apply_type": "form",
            "apply_payload": {
                "form_url": form_url,
                "portal_url": form_url
            }
        }

    # 3. Check for WhatsApp
    # 3a. Explicit wa.me / whatsapp links
    wa_match = WHATSAPP_LINK_REGEX.search(combined)
    if wa_match:
        phone = wa_match.group(1) or wa_match.group(2)
        return {
            "apply_type": "whatsapp",
            "apply_payload": {
                "phone": normalize_phone_number(phone) if phone else "",
                "whatsapp_url": wa_match.group(0)
            }
        }

    # 3b. Shortlink or link directly following WhatsApp prompt
    wa_shortlink_match = re.search(r'(?:whatsapp|واتساب|واتس)[^\n\r:–—]{0,35}[\s:–—]+(https?://[^\s<>"\']+)', desc, re.IGNORECASE)
    if wa_shortlink_match:
        wa_url = wa_shortlink_match.group(1).rstrip('.,;)]}>"')
        return {
            "apply_type": "whatsapp",
            "apply_payload": {
                "whatsapp_url": wa_url,
                "phone": ""
            }
        }

    # 3c. Valid Egyptian / Gulf mobile numbers near triggers or in WhatsApp-sourced posts
    phone_candidates = EGYPT_PHONE_REGEX.findall(desc) + GULF_PHONE_REGEX.findall(desc)
    for cand in phone_candidates:
        cleaned = normalize_phone_number(cand)
        if cleaned:
            has_trigger = any(t in desc.lower() for t in WHATSAPP_TRIGGERS)
            if has_trigger or cleaned.startswith("201"):
                return {
                    "apply_type": "whatsapp",
                    "apply_payload": {
                        "phone": cleaned,
                        "whatsapp_url": f"https://wa.me/{cleaned}"
                    }
                }

    # 4. Check for Known ATS Platforms in job_url, apply_url, or description
    for ats_name, domains in ATS_PATTERNS.items():
        if any(dom in url_lower or dom in apply_url_lower or dom in desc.lower() for dom in domains):
            ats_target = apply_url if any(dom in apply_url_lower for dom in domains) else url
            for dom in domains:
                if dom in desc.lower():
                    m = re.search(rf'https?://[^\s<>"\']*?{re.escape(dom)}[^\s<>"\']*', desc, re.IGNORECASE)
                    if m:
                        ats_target = m.group(0).rstrip('.,;)]}>"')
                        break
            return {
                "apply_type": "platform",
                "apply_payload": {
                    "platform": ats_name,
                    "portal_url": ats_target,
                    "is_direct_employer_link": True
                }
            }

    # 5. Check for Easy Apply on LinkedIn, Indeed, or Glassdoor
    if is_easy_apply_flag is True or "easy_apply" in url_lower or "ea=1" in apply_url_lower:
        return {
            "apply_type": "easy_apply",
            "apply_payload": {
                "platform": f"{site}_easy_apply" if site else "easy_apply",
                "job_url": url
            }
        }
    if "easy apply" in desc.lower() and site in ["glassdoor", "indeed", "linkedin"]:
        return {
            "apply_type": "easy_apply",
            "apply_payload": {
                "platform": f"{site}_easy_apply",
                "job_url": url
            }
        }

    # 6. Check for Social Hiring Posts (LinkedIn Posts, etc.)
    if site in ["linkedin_posts", "lnkd"] or "/posts/" in url_lower or "lnkd.in" in url_lower:
        return {
            "apply_type": "social_post",
            "apply_payload": {
                "platform": "linkedin_post",
                "post_url": url
            }
        }

    def _is_aggregator(u: str) -> bool:
        if not u:
            return False
        try:
            host = urllib.parse.urlparse(u).netloc.lower()
            return any(agg in host for agg in ['glassdoor.', 'indeed.', 'linkedin.', 'wuzzuf.', 'bayt.', 'tanqeeb.'])
        except Exception:
            return False

    # 7. Distinct external application link (employer career portal, direct ATS, or partner redirect)
    target_apply_url = apply_url
    if not target_apply_url or target_apply_url == url:
        # Check if description has an authentic employer career/apply link
        career_matches = re.findall(r'https?://[^\s<>"\']+(?:/careers?|/jobs?|/apply|jobdetail|search-jobs)[^\s<>"\']*', desc, re.IGNORECASE)
        for cand in career_matches:
            cand_clean = cand.rstrip('.,;)]}>"\'')
            if not _is_aggregator(cand_clean) and not any(ign in cand_clean.lower() for ign in ['facebook.', 'twitter.', 'google.']):
                target_apply_url = cand_clean
                break

    if target_apply_url and target_apply_url != url and not is_easy_apply_flag:
        is_direct_employer = not _is_aggregator(target_apply_url)
        return {
            "apply_type": "manual",
            "apply_payload": {
                "portal_url": target_apply_url,
                "job_url": url,
                "source": "employer_site" if (is_direct_employer or site in ["glassdoor", "indeed"]) else (site or "external"),
                "is_direct_employer_link": is_direct_employer
            }
        }

    # 8. Glassdoor job requiring external application ("Apply on employer site" / directApply is false)
    if site == "glassdoor" and (is_easy_apply_flag is False or "employer site" in desc.lower() or "company site" in desc.lower()):
        effective_portal = target_apply_url or url
        is_direct = bool(target_apply_url and not _is_aggregator(target_apply_url))
        return {
            "apply_type": "manual",
            "apply_payload": {
                "portal_url": effective_portal,
                "job_url": url,
                "source": "employer_site",
                "is_direct_employer_link": is_direct
            }
        }

    # 8b. Indeed job with explicit external redirect ("Apply on company site")
    if site == "indeed" and (is_easy_apply_flag is False or "apply on company site" in desc.lower() or "apply on employer site" in desc.lower()):
        effective_portal = target_apply_url or url
        is_direct = bool(target_apply_url and not _is_aggregator(target_apply_url))
        return {
            "apply_type": "manual",
            "apply_payload": {
                "portal_url": effective_portal,
                "job_url": url,
                "source": "employer_site",
                "is_direct_employer_link": is_direct
            }
        }

    # 9. Native Job Boards
    for domain_key, board_name in JOB_BOARD_DOMAINS.items():
        if domain_key in url_lower or domain_key in site:
            return {
                "apply_type": "job_board",
                "apply_payload": {
                    "board_name": board_name,
                    "job_url": url
                }
            }

    # 10. Default to Manual External Link
    return {
        "apply_type": "manual",
        "apply_payload": {
            "job_url": url
        }
    }
