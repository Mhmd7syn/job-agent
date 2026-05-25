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
    # Core AI/ML
    "AI Engineer", "Machine Learning Engineer", "Computer Vision", "NLP",
    
    # Core Data
    "Data Scientist", "Data Analyst", 
    
    # Instructing
    "AI Instructor", "Python Instructor", "Data Science Instructor", "Programming Instructor", "Data Analyst Instructor",
    
    # Arabic
    "مهندس ذكاء اصطناعي", "عالم بيانات", "محلل بيانات", "محاضر بايثون", "مدرب برمجة"
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
    
    # NLP & GenAI
    "nlp", "nltk", "tf-idf", "tokenizer", "llm", "transformers", "huggingface",
    
    # Deployment & Tools
    "flask", "fastapi", "restful api", "api", "git", "github", "jupyter", "linux"
]

NICE_TO_HAVE_SKILLS = [
    # General & Concepts
    'software', 'backend', 'data engineering',
    
    # LLMs & Generative AI
    'genai', 'prompt engineering', 'langchain', 'llamaindex', 'rag', 'openai',
    
    # ML & NLP Ecosystem
    'xgboost', 'lightgbm', 'spacy', 'scipy', 'statistics', 'a/b testing',
    
    # Business Intelligence & Analytics
    'power bi', 'tableau', 'excel', 'looker', 'qlik', 'dax',
    
    # Cloud, MLOps & Deployment
    'aws', 'azure', 'gcp', 'docker', 'kubernetes', 'mlops', 'ci/cd',
    
    # Big Data & Databases
    'spark', 'airflow', 'snowflake', 'bigquery', 'nosql', 'mongodb', 'postgresql', 'etl',
    
    # Mentorship & Training
    'programming', 'coding', 'instructor', 'trainer', 'teacher', 'mentor'
]

EXCLUDE_KEYWORDS = ["senior", "lead", "manager", "principal", "staff", "head", "director", "vp", "architect", "supervisor", "executive"]

EXCLUDED_COMPANIES = []
FAVORITE_COMPANIES = [
    # Multinationals & Big Tech
    "microsoft", "valeo", "ibm", "vodafone", "orange", "amazon", "dell", "siemens", "teradata",
    
    # Top Egyptian Tech & Data Teams
    "instabug", "swvl", "fawry", "talabat", "mnt-halan", "robusta", "e-finance", "cib",
    
    # Top AI & Data Science Specific Companies in Egypt
    "synapse analytics", "dxwand", "avidbeam", "affectiva", "optomatica", "tensor",
    
    # Instructing & Training Academies
    "iti", "information technology institute", "nti", "epsilon ai", "route", "amit", "ischool", "alx"
]

LOCATION = ["Egypt"]
TARGET_LOCATIONS = [
    "cairo", "giza", "new capital", "administrative capital", 
    "maadi", "masr el gedida", "heliopolis", "nasr city", 
    "new cairo", "tagamoa", "6th of october", "october", 
    "sheikh zayed", "zayed", "shorouk", "obour", "badr", "10th of ramadan",
    "smart village"
]

TARGET_LEVELS = ["junior", "fresh", "student", "intern", "entry", "graduate", "trainee", "entry-level", "undergrad"]

SITES = ["linkedin", "indeed", "google"]
USE_WUZZUF = True
SCRAPE_LINKEDIN_POSTS = True
RESULTS_PER_TERM = 15
HOURS_OLD = 7 * 24
MAX_JOBS_TO_SEND = 10

USER_BRIEF = """
I am a Junior/Entry-level professional in AI and Data Science located in Egypt.
I am looking for roles related to Machine Learning, Data Science, AI Engineering, and instructing/training positions.
My core skills include Python, SQL, Machine Learning, Deep Learning, and Computer Vision.
I prefer Junior, Fresh Graduate, Intern, or Entry-level positions and want to avoid Senior, Lead, or Managerial roles.
"""
