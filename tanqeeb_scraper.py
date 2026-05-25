import requests
import urllib.parse
from bs4 import BeautifulSoup
import pandas as pd
import time
import datetime
import logging
import sys
import os

# Add the current directory to sys.path to allow importing from llm_parser
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from llm_parser import extract_feed_posts_with_ai

def fetch_with_retries(url, retries=3, timeout=15):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    for attempt in range(retries):
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            if response.status_code == 200:
                return response
        except Exception as e:
            logging.warning(f"    (Tanqeeb network issue. Retrying {attempt+1}/{retries}...)")
            time.sleep(2)
    return None

def scrape_tanqeeb(search_term, location, results_wanted=15, hours_old=None):
    jobs = []
    query = search_term
    if location.lower() == "worldwide" or location.lower() == "remote":
        query += " remote"
        
    url = f"https://egypt.tanqeeb.com/jobs/search?keywords={urllib.parse.quote(query)}"
    
    response = fetch_with_retries(url)
    if not response:
        return pd.DataFrame()
        
    try:
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # We will extract text and append links so Gemini can find the job URLs
        content_text = ""
        for a in soup.find_all('a'):
            href = a.get('href', '')
            text = a.get_text(separator=' ', strip=True)
            if text and href and ('job' in href.lower() or 'role' in href.lower() or len(text) > 5):
                # Ensure it's a full URL
                if href.startswith('/'):
                    href = "https://egypt.tanqeeb.com" + href
                content_text += f"Job Link: {href}\nTitle/Text: {text}\n\n"
        
        # Also grab general text from paragraphs or divs to give Gemini context about companies and descriptions
        for div in soup.find_all(['p', 'span', 'div']):
            # Filter out tiny elements to reduce noise
            text = div.get_text(separator=' ', strip=True)
            if len(text) > 30 and len(text) < 500:
                content_text += f"{text}\n"

        # Limit to 20k characters to avoid token limits
        content_text = content_text[:20000]
        
        if not content_text:
            return pd.DataFrame()
            
        ai_data = extract_feed_posts_with_ai(content_text)
        
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
                        'site': 'tanqeeb',
                        'date_posted': datetime.datetime.now().date()
                    })
        else:
            logging.warning(f"⚠️ Tanqeeb AI Parsing Error: {ai_data.get('error') if ai_data else 'Unknown'}")
            
    except Exception as e:
        logging.error(f"⚠️ Tanqeeb Scraper Error: {e}")
        
    return pd.DataFrame(jobs)

if __name__ == "__main__":
    print("Testing Tanqeeb Scraper...")
    df = scrape_tanqeeb("software engineer", "egypt", 5)
    print(df.head())
