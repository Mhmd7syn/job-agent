import urllib.parse
import pandas as pd
import time
import datetime
import logging
import sys
import os

# Add the current directory to sys.path to allow importing from llm_parser
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from llm_parser import extract_feed_posts_with_ai
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

def scrape_bayt(search_term, location, results_wanted=15, hours_old=None):
    jobs = []
    query = search_term
    if location.lower() == "worldwide" or location.lower() == "remote":
        query += " remote"
        loc_path = "international"
    else:
        # Just use international with the loc parameter or path for simplicity
        loc_path = "international"

    url = f"https://www.bayt.com/en/{loc_path}/jobs/?q={urllib.parse.quote(query)}"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        Stealth().apply_stealth_sync(page)
        
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=40000)
            time.sleep(3)
            
            page.mouse.wheel(0, 1000)
            time.sleep(2)
            
            page_text = page.evaluate('''() => {
                let text = "";
                let links = document.querySelectorAll('a');
                for (let a of links) {
                    let href = a.href;
                    let inner = a.innerText.trim();
                    if (href && inner && href.includes('/job/')) {
                        text += `Job Link: ${href}\\nTitle: ${inner}\\n`;
                    }
                }
                text += "\\n" + document.body.innerText;
                return text;
            }''')

            page_text = page_text[:20000]

            if not page_text.strip():
                browser.close()
                return pd.DataFrame()

            ai_data = extract_feed_posts_with_ai(page_text)
            
            if ai_data and not ai_data.get("error"):
                jobs_list = ai_data.get("jobs", [])
                for job in jobs_list:
                    if job.get("is_job") and len(jobs) < results_wanted:
                        job_url = job.get('job_url', '')
                        if not job_url:
                            job_url = url
                        
                        jobs.append({
                            'title': job.get('title', 'Unknown'),
                            'company': job.get('company', 'Unknown'),
                            'location': job.get('location', location),
                            'job_url': job_url,
                            'job_type': 'Not specified',
                            'description': job.get('description', ''),
                            'is_remote': 'remote' in query.lower() or 'remote' in str(job.get('location', '')).lower(),
                            'site': 'bayt',
                            'date_posted': datetime.datetime.now().date()
                        })
            else:
                logging.warning(f"⚠️ Bayt AI Parsing Error: {ai_data.get('error') if ai_data else 'Unknown'}")
                
        except Exception as e:
            logging.error(f"⚠️ Bayt Scraper Error: {e}")
        finally:
            browser.close()
            
    return pd.DataFrame(jobs)

if __name__ == "__main__":
    print("Testing Bayt Scraper...")
    df = scrape_bayt("data scientist", "egypt", 5)
    print(df.head())
