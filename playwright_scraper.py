import os
import time
import json
import re
import urllib.parse
import random
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
import sys
from google import genai

if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(BASE_DIR, '.env')
USER_DATA_DIR = os.path.join(BASE_DIR, "playwright_profile")
load_dotenv(dotenv_path=env_path)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if GEMINI_API_KEY:
    client = genai.Client(api_key=GEMINI_API_KEY)
else:
    client = None

def auto_login_if_needed(page):
    email = os.getenv("LINKEDIN_EMAIL")
    password = os.getenv("LINKEDIN_PASSWORD")
    
    # Check if we are on a login page or authwall, or if login fields exist
    if "login" in page.url or "authwall" in page.url or page.query_selector('input[id="username"]') or page.query_selector('input[id="session_key"]'):
        if email and password:
            print("🔐 Playwright is logged out. Attempting auto-login...")
            try:
                page.goto("https://www.linkedin.com/login")
                page.wait_for_load_state("domcontentloaded")
                time.sleep(random.uniform(2, 4))
                
                if page.query_selector('input[id="username"]'):
                    page.fill('input[id="username"]', email)
                    page.fill('input[id="password"]', password)
                    page.click('button[type="submit"]')
                elif page.query_selector('input[id="session_key"]'):
                    page.fill('input[id="session_key"]', email)
                    page.fill('input[id="session_password"]', password)
                    page.click('button[data-id="sign-in-form__submit-btn"]') or page.click('button[type="submit"]')
                    
                time.sleep(random.uniform(3, 5))
                if "challenge" in page.url:
                    print("⚠️ LinkedIn is asking for a security check. Please run linkedin_login.py manually.")
                else:
                    print("✅ Auto-login submitted!")
            except Exception as e:
                print(f"⚠️ Auto-login error: {e}")
        else:
            print("❌ Playwright is logged out but LINKEDIN_EMAIL/LINKEDIN_PASSWORD not in .env")

def extract_job_with_ai(post_text):
    """Uses Google Gemini to extract job details from a raw post."""
    if not GEMINI_API_KEY:
        return {"error": "No Gemini API Key"}
        
    prompt = f"""
    You are an expert HR assistant. Read the following LinkedIn post and extract the job details.
    If the post is NOT a job listing (e.g. just a generic post, an article, or someone looking for a job), set "is_job" to false.
    If it IS a job listing, extract the job details.
    
    Post:
    {post_text}
    """
    
    from pydantic import BaseModel, Field
    from google.genai import types
    
    class JobExtraction(BaseModel):
        is_job: bool
        title: str = Field(default="Not specified")
        company: str = Field(default="Not specified")
        location: str = Field(default="Not specified")
        apply_method: str = Field(default="Not specified")
        
    for attempt in range(5):
        try:
            # Use a fast, free model with the new SDK
            response = client.models.generate_content(
                model='gemini-flash-lite-latest',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=JobExtraction,
                )
            )
            
            data = json.loads(response.text)
            return data
        except Exception as e:
            if "429" in str(e) or "503" in str(e):
                print(f"    (API issue ({str(e)[:15]}...). Waiting 60s before retry {attempt+1}/5...)")
                import time
                time.sleep(60)
                continue
            return {"error": str(e)}
            
    return {"error": "Exceeded retries for 429"}

def scrape_linkedin_posts_playwright(keyword):
    found_posts = []

    with sync_playwright() as p:

        context = p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=True
        )


        page = context.pages[0] if context.pages else context.new_page()
        Stealth().apply_stealth_sync(page)
        
        # Format the search URL for LinkedIn Posts
        encoded_keyword = urllib.parse.quote(keyword)
        search_url = f"https://www.linkedin.com/search/results/content/?keywords={encoded_keyword}&origin=GLOBAL_SEARCH_HEADER"
        
        try:
            page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(random.uniform(2, 4))
            
            auto_login_if_needed(page)
            
            if "login" in page.url or "authwall" in page.url:
                page.goto(search_url, wait_until="domcontentloaded", timeout=60000)

            
            # Wait a few seconds for the feed to load fully
            time.sleep(5)
            
            # Scroll down to load more posts (simulate human behavior)
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
                    
        except Exception as e:

            print(f"⚠️ Error during Playwright execution: {e}")
            
        context.close()

        
        
    return found_posts

def scrape_linkedin_jobs_playwright(term, location, results_wanted=5, hours_old=None):
    """Scrapes regular LinkedIn Jobs using the authenticated Playwright session."""
    import urllib.parse
    import datetime
    import random
    import pandas as pd
    
    jobs = []
    
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=True
        )
        page = context.pages[0] if context.pages else context.new_page()
        Stealth().apply_stealth_sync(page)
        
        # Build search URL
        encoded_term = urllib.parse.quote(term)
        encoded_loc = urllib.parse.quote(location)
        
        url = f"https://www.linkedin.com/jobs/search/?keywords={encoded_term}&location={encoded_loc}"
        if hours_old:
            seconds_old = hours_old * 3600
            url += f"&f_TPR=r{seconds_old}"
            
        print(f"🔍 Searching LinkedIn Jobs (Playwright): {term} in {location}")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=40000)
            time.sleep(random.uniform(3, 5))
            
            auto_login_if_needed(page)
            
            if "login" in page.url or "authwall" in page.url:
                page.goto(url, wait_until="domcontentloaded", timeout=40000)
                time.sleep(random.uniform(3, 5))
            
            # Scroll a bit to load job list
            for _ in range(3):
                page.mouse.wheel(0, 1000)
                time.sleep(1)
                
            # Extract job links
            links = page.evaluate('''() => {
                const anchors = Array.from(document.querySelectorAll('a'));
                const jobLinks = new Set();
                anchors.forEach(a => {
                    if (a.href && (a.href.includes('/jobs/view/') || a.href.includes('currentJobId='))) {
                        let cleanUrl = a.href.split('?')[0];
                        if (a.href.includes('currentJobId=')) {
                            const params = new URLSearchParams(a.search);
                            if (params.get('currentJobId')) {
                                cleanUrl = 'https://www.linkedin.com/jobs/view/' + params.get('currentJobId');
                            }
                        }
                        jobLinks.add(cleanUrl);
                    }
                });
                return Array.from(jobLinks);
            }''')
            
            # Limit to results_wanted
            links = links[:results_wanted]
            
            for job_url in links:
                try:
                    page.goto(job_url, wait_until="domcontentloaded", timeout=25000)
                    time.sleep(random.uniform(2, 4))
                    
                    # Try clicking "See more" if needed
                    see_more_btn = page.query_selector('.jobs-description__footer-button') or \
                                   page.query_selector('button[aria-label="Click to see more description"]')
                    if see_more_btn:
                        try:
                            see_more_btn.click(timeout=3000)
                            time.sleep(1)
                        except:
                            pass
                            
                    title = "Unknown"
                    title_elem = page.query_selector('h1')
                    if title_elem: title = title_elem.inner_text().strip()
                    
                    company = "Unknown"
                    comp_elem = page.query_selector('.jobs-unified-top-card__company-name') or \
                                page.query_selector('.job-details-jobs-unified-top-card__company-name') or \
                                page.query_selector('.jobs-company-name')
                    if comp_elem: company = comp_elem.inner_text().strip()
                    
                    loc = location
                    loc_elem = page.query_selector('.jobs-unified-top-card__bullet') or \
                               page.query_selector('.job-details-jobs-unified-top-card__bullet') or \
                               page.query_selector('.jobs-unified-top-card__primary-description')
                    if loc_elem: 
                        loc_text = loc_elem.inner_text().strip()
                        # Sometimes primary description contains "Company · Location · Posted"
                        loc = loc_text.split('·')[0].strip() if '·' in loc_text else loc_text
                    
                    desc = ""
                    desc_elem = page.query_selector('#job-details') or \
                                page.query_selector('.jobs-description__content') or \
                                page.query_selector('.jobs-description-content__text') or \
                                page.query_selector('article')
                    if desc_elem: desc = desc_elem.inner_text().strip()
                    
                    if title != "Unknown":
                        jobs.append({
                            'title': title,
                            'company': company,
                            'location': loc,
                            'job_url': job_url,
                            'description': desc,
                            'site': 'linkedin',
                            'is_remote': 'remote' in loc.lower(),
                            'date_posted': datetime.date.today(),
                            'job_type': 'Not specified'
                        })
                    
                except Exception as e:
                    print(f"⚠️ Failed to parse job {job_url}: {e}")
                    
        except Exception as e:
            print(f"⚠️ LinkedIn Search failed for {term}: {e}")
            
        context.close()
        
    return pd.DataFrame(jobs)

def get_posts_as_dataframe(term, loc):
    """Integrates with job_agent.py by returning a pandas DataFrame."""
    import pandas as pd
    from datetime import date
    
    keyword = f"hiring {term} {loc}"
    posts = scrape_linkedin_posts_playwright(keyword)
    
    valid_jobs = []
    for i, p in enumerate(posts):
        ai_data = extract_job_with_ai(p['text'])

        
        if ai_data and not ai_data.get("error"):
            if ai_data.get("is_job"):
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
        else:

            print(f"⚠️ Error from Gemini: {ai_data.get('error') if ai_data else 'Unknown'}")
            
        time.sleep(5) # Avoid Gemini Rate Limits
            
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
                time.sleep(5) # Avoid rate limits
            print("-" * 50)
    else:
        print("\nNo posts were found. Check your cookie or search terms.")
