import os
import time
import json
import re
import urllib.parse
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
import sys
from google import genai

if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(BASE_DIR, '.env')
load_dotenv(dotenv_path=env_path)

LINKEDIN_LI_AT = os.getenv("LINKEDIN_LI_AT")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if GEMINI_API_KEY:
    client = genai.Client(api_key=GEMINI_API_KEY)
else:
    client = None

def extract_job_with_ai(post_text):
    """Uses Google Gemini to extract job details from a raw post."""
    if not GEMINI_API_KEY:
        return {"error": "No Gemini API Key"}
        
    prompt = f"""
    You are an expert HR assistant. Read the following LinkedIn post and extract the job details into a strict JSON format.
    If the post is NOT a job listing (e.g. just a generic post, an article, or someone looking for a job), return {{"is_job": false}}.
    If it IS a job listing, return exactly this JSON structure:
    {{
      "is_job": true,
      "title": "Job Title",
      "company": "Company Name (if mentioned, else 'Not specified')",
      "location": "Location (if mentioned, else 'Not specified')",
      "apply_method": "Email address, link, or instruction (e.g., 'DM me')"
    }}
    
    Post:
    {post_text}
    """
    
    try:
        # Use a fast, free model with the new SDK
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        
        # Clean up response if it contains markdown formatting
        text = response.text
        match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
        if match:
            text = match.group(1)
            
        data = json.loads(text)
        return data
    except Exception as e:
        return {"error": str(e)}

def scrape_linkedin_posts_playwright(keyword):
    if not LINKEDIN_LI_AT:
        print("❌ Error: Please add LINKEDIN_LI_AT to your .env file.")
        return []

    print(f"🚀 Launching Playwright browser (invisible)...")
    found_posts = []

    with sync_playwright() as p:
        # Launch browser in headless mode
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()

        # Add the authentication cookie
        context.add_cookies([{
            "name": "li_at",
            "value": LINKEDIN_LI_AT,
            "domain": ".www.linkedin.com",
            "path": "/"
        }])

        page = context.new_page()
        
        # Format the search URL for LinkedIn Posts
        encoded_keyword = urllib.parse.quote(keyword)
        search_url = f"https://www.linkedin.com/search/results/content/?keywords={encoded_keyword}&origin=GLOBAL_SEARCH_HEADER"
        
        print(f"🔍 Navigating to LinkedIn search for: '{keyword}'...")
        try:
            page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
            
            # Wait a few seconds for the feed to load fully
            time.sleep(5)
            
            # Scroll down to load more posts (simulate human behavior)
            print("📜 Scrolling down to load more results...")
            for i in range(3):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(4)
                
            # Extract post elements
            # LinkedIn feed updates usually have this class name
            post_elements = page.query_selector_all("div.feed-shared-update-v2")
            
            for el in post_elements:
                text_content = el.inner_text()
                if text_content and len(text_content.strip()) > 20:
                    # Clean up the text a bit (LinkedIn often includes "Like", "Comment", "Share" text)
                    clean_text = text_content.strip()
                    found_posts.append({
                        "text": clean_text
                    })
                    
            print(f"✅ Successfully extracted {len(found_posts)} posts.")
        except Exception as e:
            print(f"⚠️ Error during Playwright execution: {e}")
            
        browser.close()
        
    return found_posts

def get_posts_as_dataframe(term, loc):
    """Integrates with job_agent.py by returning a pandas DataFrame."""
    import pandas as pd
    from datetime import date
    
    keyword = f"hiring {term} {loc}"
    posts = scrape_linkedin_posts_playwright(keyword)
    
    valid_jobs = []
    for p in posts:
        ai_data = extract_job_with_ai(p['text'])
        if ai_data and not ai_data.get("error") and ai_data.get("is_job"):
            valid_jobs.append({
                'title': ai_data.get('title', 'Unknown'),
                'company': ai_data.get('company', 'Unknown'),
                'location': ai_data.get('location', loc),
                'job_url': ai_data.get('apply_method', 'No link provided'),
                'description': p['text'],
                'is_remote': 'remote' in str(ai_data.get('location', '')).lower(),
                'date_posted': date.today(),
                'job_type': 'Not specified',
                'site': 'linkedin_posts'
            })
            
    if valid_jobs:
        return pd.DataFrame(valid_jobs)
    return pd.DataFrame()

if __name__ == "__main__":
    print("--- Playwright LinkedIn Post Scraper ---")
    if not GEMINI_API_KEY:
        print("⚠️ Warning: GEMINI_API_KEY not found in .env. AI Extraction will be disabled.\n")
        
    posts = scrape_linkedin_posts_playwright("hiring data scientist egypt")
    
    if posts:
        print(f"\n--- Processing {len(posts)} Posts with Gemini AI ---")
        for i, p in enumerate(posts[:3]):
            print(f"\n📝 Post #{i+1} Original Text:")
            preview = p['text'][:200].replace('\n', ' ') + "..." if len(p['text']) > 200 else p['text'].replace('\n', ' ')
            print(f"[{preview}]")
            
            if GEMINI_API_KEY:
                print("🧠 Gemini Extraction:")
                ai_data = extract_job_with_ai(p['text'])
                print(json.dumps(ai_data, indent=2, ensure_ascii=False))
            print("-" * 50)
    else:
        print("\nNo posts were found. Check your cookie or search terms.")
