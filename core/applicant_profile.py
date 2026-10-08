import os
import json
import logging
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE_PATH = os.path.join(BASE_DIR, "core", "candidate_profile.json")

DEFAULT_RESUME_DIR = r"D:\OneDrive - Faculty of Computer and Information Sciences (Ain Shams University)\my life\CV or Resume"

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
    resume_base_dir: str = DEFAULT_RESUME_DIR

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
    Scans the resume directory where subfolders match role titles.
    Finds the candidate's PDF resume in each role folder while ignoring
    Shared/, build scripts, .tex files, and ATS review notes.
    """
    target_dir = base_dir or load_profile().get("personal_info", {}).get("resume_base_dir", DEFAULT_RESUME_DIR)
    
    result = {
        "base_dir": target_dir,
        "exists": os.path.exists(target_dir),
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
    Returns the absolute path to the PDF resume matching the target role title.
    Uses exact match, role-term synonym mapping, and keyword scoring.
    """
    scan = scan_resume_directory()
    roles = scan.get("roles_found", {})
    if not roles:
        return None
        
    # 1. Exact match
    if role_title in roles and roles[role_title].get("primary_cv"):
        return roles[role_title]["primary_cv"]["path"]
        
    rt_lower = role_title.lower()
    
    # 2. Case-insensitive substring match against folder names
    for r_name, info in roles.items():
        if (r_name.lower() in rt_lower or rt_lower in r_name.lower()) and info.get("primary_cv"):
            return info["primary_cv"]["path"]
            
    # 3. Known role alias / keyword mapping
    role_keywords = {
        "Data Analytics & BI": ["analyst", "analytics", "bi", "business intelligence", "power bi", "tableau", "reporting"],
        "Data Science & Machine Learning": ["data scientist", "data science", "machine learning", "ml engineer", "predictive", "nlp", "deep learning"],
        "Computer Vision & AI": ["computer vision", "vision", "opencv", "yolo", "image processing", "ai engineer"],
        "Teaching & STEM Instructor": ["instructor", "trainer", "teacher", "teaching", "stem", "robotics", "curriculum", "lecturer"]
    }
    
    # Calculate best match score by keywords
    best_role = None
    best_score = 0
    for r_name, keywords in role_keywords.items():
        if r_name in roles and roles[r_name].get("primary_cv"):
            score = sum(1 for kw in keywords if kw in rt_lower)
            if score > best_score:
                best_score = score
                best_role = r_name
                
    if best_role and best_score > 0:
        return roles[best_role]["primary_cv"]["path"]
            
    # 4. Fallback to any valid CV found
    for info in roles.values():
        if info.get("primary_cv"):
            return info["primary_cv"]["path"]
            
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
