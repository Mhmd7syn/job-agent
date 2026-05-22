import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(BASE_DIR, '.env')
load_dotenv(dotenv_path=env_path)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
LINKEDIN_EMAIL = os.getenv("LINKEDIN_EMAIL")
LINKEDIN_PASSWORD = os.getenv("LINKEDIN_PASSWORD")

SEARCH_TERMS = [
    "AI Engineer"
]

RESUME_KEYWORDS = [
    # Programming & Core
    "python", "sql", "java", "c++", "oop", "data structures",
    
    # ML & Deep Learning
    "artificial intelligence", "ai", "machine learning", "ml", "deep learning", "tensorflow", "keras", 
    "pytorch", "scikit-learn", "random forest", "smote", "shap",
    
    # Data Science & Analytics
    "pandas", "numpy", "matplotlib", "seaborn", "feature engineering", 
    "exploratory data analysis", "eda", "minmaxscaler", "multicollinearity", "vif",
    
    # Computer Vision
    "computer vision", "opencv", "cnn", "yolo", "semantic segmentation", 
    "deeplabv3", "resnet", "clip", "vit", "efficientnet", "inception", "albumentations",
    
    # NLP
    "nlp", "nltk", "tf-idf", "tokenizer",
    
    # Deployment & Tools
    "flask", "restful api", "api", "git", "github", "jupyter", "geopandas"
]

NICE_TO_HAVE_SKILLS = [
    # General & Concepts
    'software', 'backend', 'data engineering',
    
    # LLMs & Generative AI
    'llm', 'genai', 'prompt engineering',
    
    # ML & NLP Ecosystem
    'xgboost', 'lightgbm', 'huggingface', 'transformers', 'spacy',
    
    # Business Intelligence & Analytics
    'power bi', 'tableau', 'excel', 'looker', 'qlik', 'dax',
    
    # Cloud, MLOps & Deployment
    'aws', 'azure', 'gcp', 'docker', 'kubernetes', 'mlops', 'fastapi', 
    
    # Big Data & Databases
    'spark', 'airflow', 'snowflake', 'bigquery', 'nosql', 'mongodb', 'postgresql',
    
    # Mentorship & Training
    'programming', 'coding', 'instructor', 'trainer', 'teacher', 'mentor'
]

EXCLUDE_KEYWORDS = ["senior", "lead", "manager", "principal", "staff", "head", "director",]

EXCLUDED_COMPANIES = []
FAVORITE_COMPANIES = [
    # Multinationals & Big Tech
    "microsoft", "valeo", "ibm", "vodafone", "orange", "amazon", "dell", "siemens", "teradata",
    
    # Top Egyptian Tech & Data Teams
    "instabug", "swvl", "fawry", "talabat", "mnt-halan", "robusta", "e-finance", "cib",
    
    # Top AI & Data Science Specific Companies in Egypt
    "synapse analytics", "dxwand", "avidbeam", "affectiva", "optomatica", "tensor",
    
    # Instructing & Training Academies
    "iti", "information technology institute", "nti", "epsilon ai", "route", "amit"
]

LOCATION = ["Egypt", "Remote"]
TARGET_LOCATIONS = [
    "cairo", "giza", "new capital", "administrative capital", 
    "maadi", "masr el gedida", "heliopolis", "nasr city", 
    "new cairo", "tagamoa", "6th of october", "october", 
    "sheikh zayed", "zayed", "shorouk", "obour", "badr", "10th of ramadan",
    "smart village"
]

TARGET_LEVELS = ["junior", "fresh", "student", "intern", "entry", "graduate", "trainee"]

SITES = ["linkedin", "indeed", "google"]
USE_WUZZUF = True
SCRAPE_LINKEDIN_POSTS = True
RESULTS_PER_TERM = 5
HOURS_OLD = 7 * 24
MAX_JOBS_TO_SEND = 10
