import os
import json
import time
import logging
from dotenv import load_dotenv
from pydantic import BaseModel, Field
import datetime

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
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_content, 'html.parser')
        scripts = soup.find_all('script', type='application/ld+json')
        for script in scripts:
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
            except json.JSONDecodeError:
                continue

            # Handle both single objects and @graph arrays
            candidates = []
            if isinstance(data, list):
                candidates = data
            elif isinstance(data, dict):
                if data.get('@type') == 'JobPosting':
                    candidates = [data]
                elif '@graph' in data:
                    candidates = data['@graph']

            for item in candidates:
                if not isinstance(item, dict):
                    continue
                if item.get('@type') != 'JobPosting':
                    continue

                # Map Schema.org fields → internal schema
                title = item.get('title', '') or item.get('name', '')
                
                # Company: hiringOrganization.name or plain string
                org = item.get('hiringOrganization', {})
                if isinstance(org, dict):
                    company = org.get('name', 'Unknown')
                elif isinstance(org, str):
                    company = org
                else:
                    company = 'Unknown'

                # Location: jobLocation.address or plain string
                loc_raw = item.get('jobLocation', {})
                if isinstance(loc_raw, list):
                    loc_raw = loc_raw[0] if loc_raw else {}
                if isinstance(loc_raw, dict):
                    addr = loc_raw.get('address', {})
                    if isinstance(addr, dict):
                        location = ', '.join(filter(None, [
                            addr.get('addressLocality', ''),
                            addr.get('addressRegion', ''),
                            addr.get('addressCountry', '')
                        ])) or 'Unknown'
                    elif isinstance(addr, str):
                        location = addr
                    else:
                        location = 'Unknown'
                elif isinstance(loc_raw, str):
                    location = loc_raw
                else:
                    location = 'Unknown'

                # Employment type normalisation
                emp_type_raw = item.get('employmentType', 'Not specified')
                if isinstance(emp_type_raw, list):
                    emp_type_raw = emp_type_raw[0] if emp_type_raw else 'Not specified'
                emp_map = {
                    'FULL_TIME': 'Full-time', 'PART_TIME': 'Part-time',
                    'CONTRACTOR': 'Contract', 'TEMPORARY': 'Temporary',
                    'INTERN': 'Internship', 'VOLUNTEER': 'Volunteer',
                    'PER_DIEM': 'Per Diem', 'OTHER': 'Not specified',
                }
                job_type = emp_map.get(str(emp_type_raw).upper(), str(emp_type_raw).title())

                # Date posted – prefer datePosted, fall back to validThrough
                date_posted = item.get('datePosted', '') or item.get('validThrough', '')
                if date_posted and 'T' in date_posted:
                    date_posted = date_posted.split('T')[0]

                # Description: strip HTML tags from Schema.org description
                desc_raw = item.get('description', '')
                if desc_raw:
                    desc_raw = BeautifulSoup(desc_raw, 'html.parser').get_text(separator=' ', strip=True)

                if not title:
                    continue  # Skip malformed entries

                logging.debug(f"    ⚡ JSON-LD hit: '{title}' @ '{company}' (zero tokens)")
                return {
                    'title': title,
                    'company': company,
                    'location': location,
                    'job_type': job_type,
                    'description': desc_raw,
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
        
    for attempt in range(5):
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
            )
            return response.text
        except Exception as e:
            if any(err in str(e) for err in ["429", "503", "10051", "10053", "10054", "10060"]):
                wait_time = 30 * (attempt + 1)
                logging.warning(f"    (API issue ({str(e)[:15]}...). Waiting {wait_time}s before retry {attempt+1}/5...)")
                time.sleep(wait_time)
                continue
            return f"Error during AI evaluation: {str(e)}"
            
    return "Error: Exceeded retries for AI evaluation."

