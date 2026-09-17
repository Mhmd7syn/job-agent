import os
import json
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # Project root
env_path = os.path.join(BASE_DIR, '.env')
load_dotenv(dotenv_path=env_path)

def decrypt_value(encrypted_val):
    if not encrypted_val:
        return None
    try:
        from cryptography.fernet import Fernet
        appdata = os.getenv('APPDATA') or os.path.expanduser('~')
        key_path = os.path.join(appdata, 'JobAgent', 'secret.key')
        if not os.path.exists(key_path):
            return encrypted_val # fallback if not encrypted or key missing
            
        with open(key_path, 'rb') as kf:
            key = kf.read()
            
        fernet = Fernet(key)
        return fernet.decrypt(encrypted_val.encode()).decode()
    except Exception:
        return encrypted_val # fallback if it wasn't encrypted to begin with

LINKEDIN_EMAIL = decrypt_value(os.getenv("LINKEDIN_EMAIL"))
LINKEDIN_PASSWORD = decrypt_value(os.getenv("LINKEDIN_PASSWORD"))
# If GEMINI_API_KEY is needed later in config, add it here. Otherwise, update it in os.environ for other modules.
if os.getenv("GEMINI_API_KEY"):
    os.environ["GEMINI_API_KEY"] = decrypt_value(os.getenv("GEMINI_API_KEY"))

TELEGRAM_BOT_TOKEN = decrypt_value(os.getenv("TELEGRAM_BOT_TOKEN"))
TELEGRAM_CHAT_ID = decrypt_value(os.getenv("TELEGRAM_CHAT_ID"))


config_json_path = os.path.join(os.path.dirname(__file__), 'config.json')
default_json_path = os.path.join(os.path.dirname(__file__), 'config.default.json')
if not os.path.exists(config_json_path) and os.path.exists(default_json_path):
    import shutil
    shutil.copy2(default_json_path, config_json_path)

_config_data = {}
ROLES = []
SEARCH_TERMS = []
ARABIC_SEARCH_TERMS = []
SITES_FOR_ARABIC = []
RESUME_KEYWORDS = []
EXCLUDE_KEYWORDS = []
EXCLUDED_COMPANIES = []
FAVORITE_COMPANIES = []
LOCATION = []
TARGET_LOCATIONS = []
TARGET_LEVELS = []
LEVEL_EXCLUDE = []
SITES = []
RESULTS_PER_TERM = 15
HOURS_OLD = 168
MAX_JOBS_TO_SEND = 10
USER_BRIEF = ""
GLOBAL_REMOTE_KEYWORDS = []
RESTRICTED_REMOTE_KEYWORDS = []
MIN_MATCHED_SKILLS = 2


def reload_config():
    """Reloads config.json and updates all module-level configuration variables in globals()."""
    global ROLES, SEARCH_TERMS, ARABIC_SEARCH_TERMS, SITES_FOR_ARABIC
    global RESUME_KEYWORDS, EXCLUDE_KEYWORDS, EXCLUDED_COMPANIES, FAVORITE_COMPANIES
    global LOCATION, TARGET_LOCATIONS, TARGET_LEVELS, LEVEL_EXCLUDE, SITES
    global RESULTS_PER_TERM, HOURS_OLD, MAX_JOBS_TO_SEND, USER_BRIEF
    global GLOBAL_REMOTE_KEYWORDS, RESTRICTED_REMOTE_KEYWORDS, MIN_MATCHED_SKILLS
    global _config_data

    target_path = config_json_path if os.path.exists(config_json_path) else default_json_path
    if not os.path.exists(target_path):
        _config_data = {}
    else:
        with open(target_path, 'r', encoding='utf-8') as f:
            _config_data = json.load(f)

    ROLES = _config_data.get("ROLES", [])
    SEARCH_TERMS = []
    for role in ROLES:
        SEARCH_TERMS.extend(role.get("english_terms", role.get("terms", [])))

    if not SEARCH_TERMS:
        SEARCH_TERMS = _config_data.get("SEARCH_TERMS", [])
    ARABIC_SEARCH_TERMS = []
    SITES_FOR_ARABIC = []

    RESUME_KEYWORDS = _config_data.get("RESUME_KEYWORDS", [])
    EXCLUDE_KEYWORDS = _config_data.get("EXCLUDE_KEYWORDS", [])
    EXCLUDED_COMPANIES = _config_data.get("EXCLUDED_COMPANIES", [])
    FAVORITE_COMPANIES = _config_data.get("FAVORITE_COMPANIES", [])

    LOCATION = _config_data.get("LOCATION", ["Egypt"])
    TARGET_LOCATIONS = _config_data.get("TARGET_LOCATIONS", [
        "cairo", "giza", "new capital", "administrative capital", 
        "maadi", "masr el gedida", "heliopolis", "nasr city", 
        "new cairo", "tagamoa", "6th of october", "october", 
        "sheikh zayed", "zayed", "shorouk", "obour", "badr", "10th of ramadan",
        "smart village"
    ])

    TARGET_LEVELS = _config_data.get("TARGET_LEVELS", [
        "Intern / Student",
        "Fresh Graduate / Entry-level",
        "Junior"
    ])
    LEVEL_EXCLUDE = _config_data.get("LEVEL_EXCLUDE", [
        "Mid-Level",
        "Senior / Lead",
        "Manager / Director"
    ])

    SITES = _config_data.get("SITES", ["linkedin", "wuzzuf", "bayt", "glassdoor", "tanqeeb", "indeed"])
    RESULTS_PER_TERM = _config_data.get("RESULTS_PER_TERM", 15)
    HOURS_OLD = _config_data.get("HOURS_OLD", 168)
    MAX_JOBS_TO_SEND = _config_data.get("MAX_JOBS_TO_SEND", 10)

    USER_BRIEF = _config_data.get("USER_BRIEF", """
I am a Junior/Entry-level professional located in my target region.
I am looking for suitable roles matching my skills and experience.
""")

    # Remote Location Boost Keywords
    GLOBAL_REMOTE_KEYWORDS = _config_data.get("GLOBAL_REMOTE_KEYWORDS", ['africa', 'middle east', 'mena', 'worldwide', 'global'])
    RESTRICTED_REMOTE_KEYWORDS = _config_data.get("RESTRICTED_REMOTE_KEYWORDS", ['us only', 'uk only', 'eu only'])

    # Scraper Specific Configurations
    MIN_MATCHED_SKILLS = _config_data.get("MIN_MATCHED_SKILLS", 2)

    import sys
    ja = sys.modules.get("job_agent")
    if ja is not None:
        ja.ROLES = ROLES
        ja.SEARCH_TERMS = SEARCH_TERMS
        ja.SITES = SITES
        ja.LOCATION = LOCATION
        ja.RESULTS_PER_TERM = RESULTS_PER_TERM
        ja.HOURS_OLD = HOURS_OLD

    return _config_data


# Initial load on module import
reload_config()
