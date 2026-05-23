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

class JobPageExtractionSchema(BaseModel):
    title: str = Field(default="Unknown")
    company: str = Field(default="Unknown")
    location: str = Field(default="Unknown")
    description: str = Field(default="")

def extract_post_with_ai(post_text):
    prompt = f"""
    You are an expert HR assistant. Read the following LinkedIn post and extract the job details.
    If the post is NOT a job listing (e.g. just a generic post, an article, or someone looking for a job), set "is_job" to false.
    If it IS a job listing, extract the job details.
    
    Post:
    {post_text}
    """
    
    if not client:
        return {"error": "No Gemini API Key"}
        
    for attempt in range(5):
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
            if "429" in str(e) or "503" in str(e) or "10053" in str(e) or "10054" in str(e):
                logging.warning(f"    (API issue ({str(e)[:15]}...). Waiting 15s before retry {attempt+1}/5...)")
                time.sleep(15)
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
        
    for attempt in range(5):
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
            if "429" in str(e) or "503" in str(e) or "10053" in str(e) or "10054" in str(e):
                logging.warning(f"    (API issue ({str(e)[:15]}...). Waiting 15s before retry {attempt+1}/5...)")
                time.sleep(15)
                continue
            return {"error": str(e)}
            
    return {"error": "Exceeded retries for 429"}
