import os
import re
import json
import logging
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE_PATH = os.path.join(BASE_DIR, "core", "candidate_profile.json")

class PersonalInfo(BaseModel):
    full_name: str = "Mohamed Hussein"
    first_name: str = "Mohamed"
    last_name: str = "Hussein"
    email: str = "mhmd7syn.contact@gmail.com"
    phone: str = "+201012345678"
    city: str = "Cairo"
    country: str = "Egypt"
    linkedin_url: str = "https://www.linkedin.com/in/mhmd7syn"
    github_url: str = "https://github.com/Mhmd7syn"
    portfolio_url: str = ""
    resume_base_dir: str = ""
    default_resume_path: str = ""

class SmartScreening(BaseModel):
    driving_license: bool = False
    military_status: str = "Exempted / Completed"
    notice_period_days: int = 30
    home_country: str = "Egypt"
    home_city: str = "Cairo"
    sponsorship_outside_home_only: bool = True
    relocate_outside_home_only: bool = True
    expected_salary_egp: int = 35000
    expected_salary_usd: int = 1500
    current_salary: str = "Negotiable"
    years_experience_by_role: Dict[str, int] = Field(default_factory=lambda: {
        "Computer Vision & AI": 0,
        "Data Science & Machine Learning": 0,
        "Data Analytics & BI": 0,
        "Teaching & STEM Instructor": 3
    })
    resumes_by_role: Dict[str, str] = Field(default_factory=dict)

class AutoApplySettings(BaseModel):
    enabled: bool = False
    batch_size_per_run: int = 3
    max_runs_per_day: int = 5
    min_relevance_score: int = 70
    channels_enabled: Dict[str, bool] = Field(default_factory=lambda: {
        "email": True,
        "whatsapp": True,
        "easy_apply": True,
        "platform": True
    })
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465
    smtp_email: str = ""
    smtp_app_password: str = ""
    email_signature_personal: str = "Best regards,\nMohamed Hussein\nmohamedh2910@gmail.com | +20 109 734 4958\nLinkedIn: linkedin.com/in/Mhmd7syn"
    whatsapp_mode: str = "deep_link"  # 'deep_link' (co-pilot) or 'web_automation' (auto-pilot)
    whatsapp_default_language: str = "auto"  # 'auto', 'arabic', 'english'

class CandidateProfile(BaseModel):
    personal_info: PersonalInfo = Field(default_factory=PersonalInfo)
    smart_screening: SmartScreening = Field(default_factory=SmartScreening)
    auto_apply_settings: AutoApplySettings = Field(default_factory=AutoApplySettings)
    custom_qa_pairs: Dict[str, str] = Field(default_factory=dict)

def get_default_profile() -> Dict[str, Any]:
    return CandidateProfile().model_dump()

def load_profile() -> Dict[str, Any]:
    if not os.path.exists(PROFILE_PATH):
        profile = get_default_profile()
        save_profile(profile)
        return profile
    try:
        with open(PROFILE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Validate through model for schema consistency
            return CandidateProfile(**data).model_dump()
    except Exception as e:
        logging.error(f"Error loading {PROFILE_PATH}: {e}")
        return get_default_profile()

def save_profile(profile_data: Dict[str, Any]) -> bool:
    try:
        validated = CandidateProfile(**profile_data).model_dump()
        os.makedirs(os.path.dirname(PROFILE_PATH), exist_ok=True)
        with open(PROFILE_PATH, "w", encoding="utf-8") as f:
            json.dump(validated, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logging.error(f"Error saving {PROFILE_PATH}: {e}")
        return False

def scan_resume_directory(base_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    Scans an optional resume directory where subfolders match role titles.
    If no base directory is provided or configured, returns an empty result.
    """
    target_dir = base_dir or load_profile().get("personal_info", {}).get("resume_base_dir", "")
    
    result = {
        "base_dir": target_dir,
        "exists": bool(target_dir and os.path.exists(target_dir)),
        "roles_found": {},
        "ignored_items": []
    }
    
    if not result["exists"]:
        return result
        
    ignored_names = {"shared", "build.bat", "build.ps1", ".git", ".vscode", "ats-review.pdf"}
    
    try:
        for entry in os.scandir(target_dir):
            if entry.name.lower() in ignored_names:
                result["ignored_items"].append(entry.name)
                continue
                
            if entry.is_dir():
                role_name = entry.name
                pdf_files = []
                cover_letters = []
                
                for f in os.scandir(entry.path):
                    if f.is_file() and f.name.lower().endswith(".pdf"):
                        if "ats" in f.name.lower() or "review" in f.name.lower():
                            result["ignored_items"].append(f"{role_name}/{f.name}")
                            continue
                        if "cover" in f.name.lower():
                            cover_letters.append({
                                "filename": f.name,
                                "path": f.path,
                                "size_kb": round(f.stat().st_size / 1024, 1)
                            })
                        else:
                            pdf_files.append({
                                "filename": f.name,
                                "path": f.path,
                                "size_kb": round(f.stat().st_size / 1024, 1)
                            })
                            
                primary_cv = pdf_files[0] if pdf_files else None
                result["roles_found"][role_name] = {
                    "folder_path": entry.path,
                    "primary_cv": primary_cv,
                    "cover_letter": cover_letters[0] if cover_letters else None,
                    "all_pdfs": pdf_files
                }
    except Exception as e:
        logging.error(f"Error scanning resume directory {target_dir}: {e}")
        result["error"] = str(e)
        
    return result

def get_resume_for_role(role_title: str) -> Optional[str]:
    """
    Returns the absolute path to the resume matching the target role or job title.
    Uses the explicit resume settings configured per role in the user settings,
    without hardcoded role paths or keyword mappings.
    """
    import core.config as app_config

    roles = getattr(app_config, "ROLES", [])
    if not roles:
        try:
            config_path = os.path.join(os.path.dirname(__file__), "config.json")
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                    roles = cdata.get("ROLES", [])
        except Exception as e:
            logging.error(f"Error loading roles from config: {e}")
            roles = []

    profile = load_profile()
    profile_resumes = profile.get("smart_screening", {}).get("resumes_by_role", {})
    default_resume = profile.get("personal_info", {}).get("default_resume_path", "").strip()

    def _resolve_valid_path(p: Optional[str]) -> Optional[str]:
        if not p or not str(p).strip():
            return None
        clean_p = str(p).strip()
        if os.path.isabs(clean_p):
            return clean_p
        resolved = os.path.join(BASE_DIR, clean_p)
        return os.path.abspath(resolved)

    if not roles and not profile_resumes:
        return _resolve_valid_path(default_resume)

    rt_lower = (role_title or "").strip().lower()

    # 1. Exact match against configured role title
    for r in roles:
        title = r.get("title", "").strip()
        if title and title.lower() == rt_lower:
            cv = r.get("resume_path") or profile_resumes.get(title)
            if cv:
                return _resolve_valid_path(cv)

    for prof_title, cv in profile_resumes.items():
        if prof_title.strip().lower() == rt_lower and cv:
            return _resolve_valid_path(cv)

    # 2. Case-insensitive substring match on role title
    for r in roles:
        title = r.get("title", "").strip()
        if title:
            t_lower = title.lower()
            if t_lower in rt_lower or rt_lower in t_lower:
                cv = r.get("resume_path") or profile_resumes.get(title)
                if cv:
                    return _resolve_valid_path(cv)

    for prof_title, cv in profile_resumes.items():
        pt_lower = prof_title.strip().lower()
        if pt_lower and (pt_lower in rt_lower or rt_lower in pt_lower) and cv:
            return _resolve_valid_path(cv)

    # 3. Match against configured search terms and title keywords from settings
    best_role = None
    best_score = 0
    rt_tokens = set(re.split(r'[\s&/,\-\+_]+', rt_lower))

    for r in roles:
        title = r.get("title", "").strip()
        cv = r.get("resume_path") or profile_resumes.get(title)
        if not cv:
            continue
        terms = r.get("english_terms", r.get("terms", []))
        score = 0

        # Exact phrase match in search terms (highest priority)
        for term in terms:
            term_clean = term.strip().lower()
            if not term_clean:
                continue
            if term_clean in rt_lower:
                score += len(term_clean) * 5
            elif rt_lower in term_clean and len(rt_lower) >= 4:
                score += len(rt_lower) * 3

        # Title words match (e.g., 'instructor', 'analyst', 'vision')
        title_tokens = [w for w in re.split(r'[\s&/,\-\+_]+', title.lower()) if len(w) >= 3 and w not in {'and', 'the', 'for'}]
        for tw in title_tokens:
            if tw in rt_tokens or (len(tw) >= 4 and tw in rt_lower):
                score += len(tw) * 3

        # Term tokens match
        for term in terms:
            for tw in re.split(r'[\s&/,\-\+_]+', term.lower()):
                if len(tw) >= 4 and tw not in {'and', 'the', 'for', 'with'} and (tw in rt_tokens or tw in rt_lower):
                    score += len(tw)

        if score > best_score:
            best_score = score
            best_role = r

    if best_role and best_score > 0:
        cv = best_role.get("resume_path") or profile_resumes.get(best_role.get("title"))
        if cv:
            return _resolve_valid_path(cv)

    # 4. Fallback: default_resume if specified, else the first configured role with a resume
    if default_resume:
        return _resolve_valid_path(default_resume)

    for r in roles:
        cv = r.get("resume_path") or profile_resumes.get(r.get("title"))
        if cv:
            return _resolve_valid_path(cv)

    for cv in profile_resumes.values():
        if cv:
            return _resolve_valid_path(cv)

    return None

def resolve_contextual_screening(job_location: str, job_country: str = "") -> Dict[str, Any]:
    """
    Resolves visa sponsorship, relocation, and driving license rules based on candidate preferences.
    """
    profile = load_profile()
    screening = profile.get("smart_screening", {})
    home_country = (screening.get("home_country") or "Egypt").lower()
    home_city = (screening.get("home_city") or "Cairo").lower()
    
    loc_str = f"{job_location} {job_country}".lower()
    
    is_in_home_country = home_country in loc_str or "egypt" in loc_str or "cairo" in loc_str or "giza" in loc_str
    is_in_home_city = home_city in loc_str or "cairo" in loc_str or "giza" in loc_str
    
    # Context-aware Sponsorship:
    # If in home country -> No sponsorship needed (False)
    # If outside home country -> Sponsorship needed (True)
    if screening.get("sponsorship_outside_home_only", True):
        requires_sponsorship = not is_in_home_country
    else:
        requires_sponsorship = False
        
    # Context-aware Relocation:
    # If in home city -> Relocation not needed (False)
    # If outside home city / country -> Relocation willing (True)
    if screening.get("relocate_outside_home_only", True):
        willing_to_relocate = not is_in_home_city
    else:
        willing_to_relocate = True
        
    return {
        "driving_license": screening.get("driving_license", False),
        "military_status": screening.get("military_status", "Exempted / Completed"),
        "notice_period_days": screening.get("notice_period_days", 30),
        "requires_visa_sponsorship": requires_sponsorship,
        "willing_to_relocate": willing_to_relocate,
        "is_home_country": is_in_home_country,
        "is_home_city": is_in_home_city
    }
