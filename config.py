import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(BASE_DIR, '.env')
load_dotenv(dotenv_path=env_path)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SEARCH_TERMS = [
    "AI Engineer", "Machine Learning Engineer", "Artificial Intelligence",
    "Data Scientist", "Data Science", 
    "Data Analyst", "Data Analysis",
    "AI Instructor", "Data Science Instructor", "Machine Learning Instructor", "Data Analytics Instructor", "Python Instructor", "Programming Instructor", "Coding Instructor"
]

USE_KEYWORD_FILTER = False
MUST_HAVE_KEYWORDS = ["pytorch", "tensorflow", "yolo", "mediapipe", "python", "computer vision", "deep learning"]

LOCATION = ["Egypt"]   # Add "Remote" here if you want to search for remote jobs
FILTER_BY_SPECIFIC_LOCATIONS = False
TARGET_LOCATIONS = [
    "cairo", "giza", "new capital", "administrative capital", 
    "maadi", "masr el gedida", "heliopolis", "nasr city", 
    "new cairo", "tagamoa", "6th of october", "october", 
    "sheikh zayed", "zayed", "shorouk", "obour", "badr", "10th of ramadan",
    "smart village"
]

FILTER_BY_LEVEL = True
TARGET_LEVELS = ["junior", "fresh", "student", "intern", "entry"]

SITES = ["linkedin", "indeed", "google"]
RESULTS_PER_TERM = 15
HOURS_OLD = 7 * 24
MAX_JOBS_TO_SEND = 10
