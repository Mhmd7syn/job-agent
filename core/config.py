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


with open(os.path.join(os.path.dirname(__file__), 'config.json'), 'r', encoding='utf-8') as f:
    _config_data = json.load(f)

ROLES = _config_data.get("ROLES", [])
SEARCH_TERMS = []
ARABIC_SEARCH_TERMS = []

for role in ROLES:
    SEARCH_TERMS.extend(role.get("english_terms", []))
    ARABIC_SEARCH_TERMS.extend(role.get("arabic_terms", []))

if not SEARCH_TERMS:
    SEARCH_TERMS = _config_data.get("SEARCH_TERMS", [])
if not ARABIC_SEARCH_TERMS:
    ARABIC_SEARCH_TERMS = _config_data.get("ARABIC_SEARCH_TERMS", [])
SITES_FOR_ARABIC = _config_data.get("SITES_FOR_ARABIC", ["wuzzuf", "linkedin"])

RESUME_KEYWORDS = _config_data.get("RESUME_KEYWORDS", [])
NICE_TO_HAVE_SKILLS = _config_data.get("NICE_TO_HAVE_SKILLS", [])
EXCLUDE_KEYWORDS = _config_data.get("EXCLUDE_KEYWORDS", [])
EXCLUDED_COMPANIES = _config_data.get("EXCLUDED_COMPANIES", [])
FAVORITE_COMPANIES = _config_data.get("FAVORITE_COMPANIES", [])

LOCATION = _config_data.get("LOCATION", ["Egypt", "Remote"])
TARGET_LOCATIONS = _config_data.get("TARGET_LOCATIONS", [
    "Cairo", "Giza", "Remote", "Global"
])

TARGET_LEVELS = _config_data.get("TARGET_LEVELS", ["Junior", "Entry-level", "Intern"])

SITES = _config_data.get("SITES", ["linkedin", "wuzzuf", "bayt", "glassdoor", "tanqeeb", "indeed"])
RESULTS_PER_TERM = _config_data.get("RESULTS_PER_TERM", 15)
HOURS_OLD = _config_data.get("HOURS_OLD", 168)
MAX_JOBS_TO_SEND = _config_data.get("MAX_JOBS_TO_SEND", 10)

USER_BRIEF = _config_data.get("USER_BRIEF", """
I am a passionate software and AI professional looking for Junior or Entry-level positions.
My core skills include Python, SQL, Machine Learning, and problem solving.
I prefer Junior, Intern, or Entry-level positions.
""")

# Remote Location Boost Keywords
GLOBAL_REMOTE_KEYWORDS = _config_data.get("GLOBAL_REMOTE_KEYWORDS", ['africa', 'middle east', 'mena', 'worldwide', 'global'])
RESTRICTED_REMOTE_KEYWORDS = _config_data.get("RESTRICTED_REMOTE_KEYWORDS", ['us only', 'uk only', 'eu only'])

# Scraper Specific Configurations
GLASSDOOR_LOC_ID = _config_data.get("GLASSDOOR_LOC_ID", 69)
