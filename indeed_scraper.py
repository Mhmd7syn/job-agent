import urllib.parse
import pandas as pd
import datetime
import logging
import sys
import os
from curl_cffi import requests

# Add the current directory to sys.path to allow importing from llm_parser
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from llm_parser import extract_feed_posts_with_ai

def scrape_indeed(search_term, location, results_wanted=15, hours_old=None):
    jobs = []
    
    url = f"https://www.indeed.com/jobs?q={urllib.parse.quote(search_term)}&l={urllib.parse.quote(location)}"
    
    try:
        import time
        response = None
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Use impersonate to mimic a Chrome browser and bypass Cloudflare
                response = requests.get(url, impersonate="chrome120", timeout=30)
                if response.status_code == 200:
                    break
            except Exception as e:
                logging.debug(f"Indeed request failed: {e}")
                
            logging.warning(f"⚠️ Indeed Scraper attempt {attempt + 1} failed. Retrying in {2 ** attempt} seconds...")
            time.sleep(2 ** attempt)
        
        if not response or response.status_code != 200:
            logging.error(f"⚠️ Indeed Scraper returned status {response.status_code if response else 'Unknown'} after {max_retries} attempts.")
            return pd.DataFrame()

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(response.text, 'html.parser')
        
        content_text = ""
        # Extract job cards
        job_cards = soup.find_all('div', class_='job_seen_beacon')
        for card in job_cards:
            a_tag = card.find('a', id=lambda x: x and x.startswith('job_'))
            if a_tag:
                href = a_tag.get('href', '')
                if href.startswith('/'):
                    href = "https://www.indeed.com" + href
                
                text = card.get_text(separator=" ", strip=True)
                if len(text) > 10:
                    content_text += f"Job Link: {href}\nJob Info: {text}\n\n"
                    
        # Fallback if specific classes didn't match
        if not content_text.strip():
            for a in soup.find_all('a'):
                href = a.get('href', '')
                if '/rc/clk' in href or 'vjk=' in href:
                    if href.startswith('/'):
                        href = "https://www.indeed.com" + href
                    text = a.get_text(separator=" ", strip=True)
                    content_text += f"Job Link: {href}\nJob Info: {text}\n\n"

        if not content_text.strip():
            return pd.DataFrame()

        ai_data = extract_feed_posts_with_ai(content_text[:20000])
        
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
                        'job_type': job.get('job_type', 'Not specified'),
                        'description': job.get('description', ''),
                        'is_remote': 'remote' in search_term.lower() or 'remote' in str(job.get('location', '')).lower(),
                        'site': 'indeed',
                        'date_posted': job.get('date_posted') or datetime.datetime.now().date()
                    })
        else:
            logging.warning(f"⚠️ Indeed AI Parsing Error: {ai_data.get('error') if ai_data else 'Unknown'}")
            
    except Exception as e:
        logging.error(f"⚠️ Indeed Scraper Error: {e}")
            
    return pd.DataFrame(jobs)

if __name__ == "__main__":
    if sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
    print("Testing Indeed Scraper...")
    df = scrape_indeed("data scientist", "egypt", 5)
    print(df.head())
