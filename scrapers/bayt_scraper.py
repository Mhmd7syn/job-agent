import urllib.parse
import pandas as pd
import datetime
import logging
from curl_cffi import requests

from core.llm_parser import extract_feed_posts_with_ai

def scrape_bayt(search_term, location, results_wanted=15, hours_old=None):
    jobs = []
    query = search_term
    
    loc_path = "egypt" if "egypt" in location.lower() else "international"
    url = f"https://www.bayt.com/en/{loc_path}/jobs/?q={urllib.parse.quote(query)}"
    
    try:
        # Use impersonate to mimic a Safari browser and bypass Cloudflare TLS fingerprints
        response = requests.get(url, impersonate="safari15_5", timeout=20)
        
        if response.status_code != 200:
            logging.error(f"⚠️ Bayt Scraper returned status {response.status_code}")
            return pd.DataFrame()

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(response.text, 'html.parser')
        
        content_text = ""
        # Extract job cards
        job_cards = soup.find_all('li', class_='has-pointer-d')
        for card in job_cards:
            title_elem = card.find('h2', class_='m0 t-regular')
            if title_elem and title_elem.find('a'):
                a_tag = title_elem.find('a')
                href = a_tag.get('href', '')
                if href.startswith('/'):
                    href = "https://www.bayt.com" + href
                title = a_tag.text.strip()
                content_text += f"Job Link: {href}\nTitle: {title}\n"
                
                # Try to get company and location
                company_elem = card.find('b', class_='p10r')
                if company_elem:
                    content_text += f"Company: {company_elem.text.strip()}\n"
                
                desc_elem = card.find('div', class_='t-small')
                if desc_elem:
                    content_text += f"Description: {desc_elem.text.strip()}\n"
                    
                content_text += "\n"

        if not content_text.strip():
            return pd.DataFrame()

        ai_data = extract_feed_posts_with_ai(content_text[:20000])
        
        if ai_data and not ai_data.get("error"):
            jobs_list = ai_data.get("jobs", [])
            # Apply hours_old cutoff that was previously ignored
            cutoff = None
            if hours_old:
                cutoff = (datetime.datetime.now() - datetime.timedelta(hours=hours_old)).date()
            for job in jobs_list:
                if job.get("is_job") and len(jobs) < results_wanted:
                    raw_date = job.get('date_posted')
                    if cutoff and raw_date:
                        try:
                            job_date = datetime.datetime.strptime(raw_date, "%Y-%m-%d").date()
                            if job_date < cutoff:
                                continue
                        except Exception:
                            pass
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
                        'is_remote': 'remote' in search_term.lower() or 'remote' in str(job.get('location', '')).lower(),
                        'site': 'bayt',
                        'date_posted': job.get('date_posted') or datetime.datetime.now().date()
                    })
        else:
            logging.warning(f"⚠️ Bayt AI Parsing Error: {ai_data.get('error') if ai_data else 'Unknown'}")
            
    except Exception as e:
        logging.error(f"⚠️ Bayt Scraper Error: {e}")
            
    return pd.DataFrame(jobs)

if __name__ == "__main__":
    if sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
    print("Testing Bayt Scraper...")
    df = scrape_bayt("data scientist", "egypt", 5)
    print(df.head())
