import os
import json
import time
import logging
from dotenv import load_dotenv
from pydantic import BaseModel, Field
import datetime
from bs4 import BeautifulSoup

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # Project root
env_path = os.path.join(BASE_DIR, '.env')
load_dotenv(dotenv_path=env_path)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if GEMINI_API_KEY:
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=GEMINI_API_KEY)
else:
    client = None

class PostExtractionSchema(BaseModel):
    is_job: bool
    title: str = Field(default="Not specified")
    company: str = Field(default="Not specified")
    location: str = Field(default="Not specified")
    job_type: str = Field(default="Not specified", description="The job type (e.g., Full-time, Part-time, Internship).")
    description: str = Field(default="")
    job_url: str = Field(default="", description="The Post URL provided at the top of the post. Do NOT use application links found inside the post.")
    date_posted: str = Field(default="", description="The date the job was posted in YYYY-MM-DD format. Calculate using today's date if relative (e.g., '3 weeks ago' or 'منذ 3 أسابيع' -> subtract 21 days from today; '2 days ago' or 'منذ يومين' -> subtract 2 days; 'yesterday' or 'أمس' -> subtract 1 day).")

class MultiplePostsExtractionSchema(BaseModel):
    jobs: list[PostExtractionSchema]


class JobPageExtractionSchema(BaseModel):
    title: str = Field(default="Unknown")
    company: str = Field(default="Unknown")
    location: str = Field(default="Unknown")
    job_type: str = Field(default="Not specified", description="The job type (e.g., Full-time, Part-time, Internship).")
    description: str = Field(default="")
    date_posted: str = Field(default="", description="The date the job was posted in YYYY-MM-DD format. Calculate using today's date if relative (e.g., '3 weeks ago' or 'منذ 3 أسابيع' -> subtract 21 days from today; '2 days ago' or 'منذ يومين' -> subtract 2 days; 'yesterday' or 'أمس' -> subtract 1 day).")


def extract_json_ld(html_content: str) -> dict | None:
    """Zero-token Schema.org JSON-LD extractor.

    Searches for a <script type="application/ld+json"> tag containing a
    Schema.org JobPosting object and maps its fields to our internal schema.
    Returns a dict on success, or None to signal Gemini fallback is needed.
    """
    try:
        from scrapers.common import extract_json_ld_job
        res = extract_json_ld_job(html_content)
        title = res.get('title')
        if title:
            date_posted = res.get('date_posted', '')
            if date_posted and 'T' in date_posted:
                date_posted = date_posted.split('T')[0]
            logging.debug(f"    ⚡ JSON-LD hit: '{title}' @ '{res.get('company', 'Unknown')}' (zero tokens)")
            return {
                'title': title,
                'company': res.get('company') or 'Unknown',
                'location': res.get('location') or 'Unknown',
                'job_type': res.get('job_type') or 'Not specified',
                'description': res.get('description') or '',
                'date_posted': date_posted,
            }
    except Exception as e:
        logging.debug(f"JSON-LD extraction error (non-fatal): {e}")
    return None


def extract_feed_posts_with_ai(feed_text):
    prompt = f"""
    You are an expert HR assistant. Read the following text from a LinkedIn search feed or job card and extract all the job listings you can find in it.
    For each job, extract the title, company, location, the post description text, and the job_url (Post URL).
    CRITICAL ON JOB URL: For job_url, you MUST extract the 'Post URL' or Job Link provided at the beginning of each block. Do NOT extract links from within the post text (like application links).
    CRITICAL ON COMPANY NAME: If the company field in the posting header is listed as 'Confidential', 'Unknown', or is missing, inspect the job description text for mentions of the hiring company (e.g., 'Advansys is looking for...', 'About [Company]', or 'We at [Company] are seeking...'). If a specific company name is revealed in the description text, extract that real company name instead of 'Confidential'.
    Ignore generic posts, articles, and people looking for jobs.
    Today's date is {datetime.date.today().isoformat()}. Use it to calculate YYYY-MM-DD from English or Arabic relative times (e.g. '1w', '2d', '1 week ago', 'منذ 3 أسابيع', 'قبل يومين', 'أمس').
    
    Feed Text:
    {feed_text}
    """
    
    if not client:
        return {"error": "No Gemini API Key"}
        
    for attempt in range(2):  # 1 retry — fail fast if quota exhausted
        try:
            response = client.models.generate_content(
                model='gemini-flash-lite-latest',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=MultiplePostsExtractionSchema,
                )
            )
            return json.loads(response.text)
        except Exception as e:
            if any(err in str(e) for err in ["429", "503", "10051", "10053", "10054", "10060"]):
                if attempt == 0:
                    logging.warning(f"    (API issue ({str(e)[:15]}...). Waiting 5s before retry...)")
                    time.sleep(5)
                    continue
            return {"error": str(e)}

    return {"error": "Exceeded retries for 429"}

def extract_job_page_with_ai(page_text):
    prompt = f"""
    You are an expert HR assistant. Read the following raw text extracted from a job board webpage and extract the structured job details.
    CRITICAL ON COMPANY NAME: If the company field is listed as 'Confidential', 'Unknown', or is missing, inspect the body text for mentions of the hiring company (e.g., 'Advansys is looking for...', 'About [Company]', or 'We at [Company] are seeking...'). If a specific company name is revealed in the description, extract that real company name instead of 'Confidential'.
    Ignore navigation menus, footers, and generic UI text. Focus on the actual job posting.
    Today's date is {datetime.date.today().isoformat()}. Use it to calculate YYYY-MM-DD from English or Arabic relative times (e.g. '1w', '2d', '1 week ago', 'منذ 3 أسابيع', 'قبل يومين', 'أمس').
    
    Webpage Text:
    {page_text}
    """
    
    if not client:
        return {"error": "No Gemini API Key"}
        
    for attempt in range(2):  # 1 retry — fail fast if quota exhausted
        try:
            response = client.models.generate_content(
                model='gemini-flash-lite-latest',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=JobPageExtractionSchema,
                )
            )
            return json.loads(response.text)
        except Exception as e:
            if any(err in str(e) for err in ["429", "503", "10051", "10053", "10054", "10060"]):
                if attempt == 0:
                    logging.warning(f"    (API issue ({str(e)[:15]}...). Waiting 5s before retry...)")
                    time.sleep(5)
                    continue
            return {"error": str(e)}

    return {"error": "Exceeded retries for 429"}

def evaluate_run_with_ai(logs_text, csv_text, user_brief=""):
    prompt = f"""
    You are an expert AI assistant evaluating a job scraping script run.
    The user wants you to evaluate the project's performance and check for any enhancements.
    
    User Profile & Preferences:
    {user_brief if user_brief else "No specific preferences provided."}
    
    Execution Logs:
    {logs_text}
    
    Found Jobs (CSV Preview):
    {csv_text}
    
    Please provide a brief evaluation of the run, noting any errors in the logs, the quality/quantity of jobs found based on the User Profile & Preferences, and suggest potential enhancements. Keep it concise and helpful.
    """
    
    if not client:
        return "No Gemini API Key found. Cannot evaluate."
        
    models_to_try = ['gemini-2.5-flash', 'gemini-flash-lite-latest']
    last_error = None

    for model_name in models_to_try:
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                if response and response.text:
                    return response.text
            except Exception as e:
                last_error = e
                if any(err in str(e) for err in ["429", "503", "10051", "10053", "10054", "10060", "UNAVAILABLE"]):
                    wait_time = 5 * (attempt + 1)
                    logging.warning(f"    (AI evaluation issue with {model_name} ({str(e)[:25]}...). Waiting {wait_time}s before retry {attempt+1}/3...)")
                    time.sleep(wait_time)
                    continue
                break
                
    return f"Error during AI evaluation: {last_error or 'Exceeded retries'}"

