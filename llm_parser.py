import os
import json
import time
import logging
from dotenv import load_dotenv
from pydantic import BaseModel, Field

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
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
    description: str = Field(default="")
    job_url: str = Field(default="")

class MultiplePostsExtractionSchema(BaseModel):
    jobs: list[PostExtractionSchema]


class JobPageExtractionSchema(BaseModel):
    title: str = Field(default="Unknown")
    company: str = Field(default="Unknown")
    location: str = Field(default="Unknown")
    description: str = Field(default="")

def extract_post_with_ai(post_text):
    prompt = f"""
    You are an expert HR assistant. Read the following LinkedIn post and extract the job details.
    If the post is NOT a job listing (e.g. just a generic post, an article, or someone looking for a job), set "is_job" to false.
    If it IS a job listing, extract the job details, including the Post URL if it is provided.
    
    Post:
    {post_text}
    """
    
    if not client:
        return {"error": "No Gemini API Key"}
        
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model='gemini-flash-lite-latest',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=PostExtractionSchema,
                )
            )
            return json.loads(response.text)
        except Exception as e:
            if any(err in str(e) for err in ["429", "503", "10051", "10053", "10054", "10060"]):
                wait_time = 10 * (attempt + 1)
                logging.warning(f"    (API issue ({str(e)[:15]}...). Waiting {wait_time}s before retry {attempt+1}/3...)")
                time.sleep(wait_time)
                continue
            return {"error": str(e)}
            
    return {"error": "Exceeded retries for 429"}

def extract_feed_posts_with_ai(feed_text):
    prompt = f"""
    You are an expert HR assistant. Read the following text from a LinkedIn search feed and extract all the job listings you can find in it.
    For each job, extract the title, company, location, the post description text, and the job_url (Post URL).
    Ignore generic posts, articles, and people looking for jobs.
    
    Feed Text:
    {feed_text}
    """
    
    if not client:
        return {"error": "No Gemini API Key"}
        
    for attempt in range(3):
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
                wait_time = 10 * (attempt + 1)
                logging.warning(f"    (API issue ({str(e)[:15]}...). Waiting {wait_time}s before retry {attempt+1}/3...)")
                time.sleep(wait_time)
                continue
            return {"error": str(e)}
            
    return {"error": "Exceeded retries for 429"}

def extract_job_page_with_ai(page_text):
    prompt = f"""
    You are an expert HR assistant. Read the following raw text extracted from a job board webpage and extract the structured job details.
    Ignore navigation menus, footers, and generic UI text. Focus on the actual job posting.
    
    Webpage Text:
    {page_text}
    """
    
    if not client:
        return {"error": "No Gemini API Key"}
        
    for attempt in range(3):
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
                wait_time = 10 * (attempt + 1)
                logging.warning(f"    (API issue ({str(e)[:15]}...). Waiting {wait_time}s before retry {attempt+1}/3...)")
                time.sleep(wait_time)
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
                model='gemini-2.5-pro',
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

