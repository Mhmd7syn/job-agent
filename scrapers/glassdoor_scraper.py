import urllib.parse
import pandas as pd
import datetime
import logging
import random

from core.llm_parser import extract_feed_posts_with_ai
from core.config import GLASSDOOR_LOC_ID
from core.database import is_job_seen

def scrape_glassdoor(search_term, location, results_wanted=15, hours_old=None, driver=None):
    jobs = []
    
    # Simple URL encoding for glassdoor (this will redirect to the right search)
    url = f"https://www.glassdoor.com/Job/jobs.htm?sc.keyword={urllib.parse.quote(search_term)}&locT=N&locId={GLASSDOOR_LOC_ID}&locKeyword={urllib.parse.quote(location)}&sortBy=date_desc"
    if hours_old:
        days = int(hours_old / 24)
        if days > 0:
            url += f"&fromAge={days}"
    
    if driver is None:
        logging.error("Glassdoor scraper requires a SeleniumBase driver.")
        return pd.DataFrame()
        
    try:
        driver.uc_open_with_reconnect(url, 4)
        try:
            driver.uc_gui_click_captcha()
        except Exception:
            pass
        
        # wait for job cards or cloudflare bypass
        try:
            driver.wait_for_element('li', timeout=10)
        except:
            pass

        from bs4 import BeautifulSoup
        html_content = driver.get_page_source()
        soup = BeautifulSoup(html_content, 'html.parser')
        
        content_text = ""
        # Extract job cards (Glassdoor usually uses li tags for jobs)
        job_cards = soup.find_all('li')
        for card in job_cards:
            a_tag = card.find('a', href=True)
            if a_tag:
                href = a_tag['href']
                if 'job-listing' in href or '/partner/' in href:
                    if href.startswith('/'):
                        href = "https://www.glassdoor.com" + href
                    if is_job_seen(href):
                        logging.debug(f"    ⏭️ Skipping known job (cached): {href}")
                        continue
                    text = card.get_text(separator=" ", strip=True)
                    if len(text) > 10:
                        content_text += f"Job Link: {href}\nJob Info: {text}\n\n"

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
                        'job_type': job.get('job_type', 'Not specified'),
                        'description': job.get('description', ''),
                        'is_remote': 'remote' in search_term.lower() or 'remote' in str(job.get('location', '')).lower(),
                        'site': 'glassdoor',
                        'date_posted': job.get('date_posted') or datetime.datetime.now().date()
                    })
        else:
            logging.warning(f"⚠️ Glassdoor AI Parsing Error: {ai_data.get('error') if ai_data else 'Unknown'}")
            
    except Exception as e:
        logging.error(f"⚠️ Glassdoor Scraper Error: {e}")
            
    return pd.DataFrame(jobs)

if __name__ == "__main__":
    if sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
    print("Testing Glassdoor Scraper...")
    df = scrape_glassdoor("data scientist", "egypt", 5)
    print(df.head())
