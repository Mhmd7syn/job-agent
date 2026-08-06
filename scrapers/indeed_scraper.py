import sys
import urllib.parse
import pandas as pd
import datetime
import logging
import random

from core.llm_parser import extract_feed_posts_with_ai
from core.database import is_job_seen

def scrape_indeed(search_term, location, results_wanted=15, hours_old=None, driver=None):
    jobs = []
    
    url = f"https://www.indeed.com/jobs?q={urllib.parse.quote(search_term)}&l={urllib.parse.quote(location)}&sort=date"
    if hours_old:
        days = int(hours_old / 24)
        if days > 0:
            url += f"&fromage={days}"
    
    if driver is None:
        logging.error("Indeed scraper requires a SeleniumBase driver.")
        return pd.DataFrame()
        
    try:
        driver.uc_open_with_reconnect(url, 4)
        try:
            driver.uc_gui_click_captcha()
        except Exception:
            pass

        # Check for Cloudflare block visually or just wait for content
        try:
            driver.wait_for_element('div.job_seen_beacon, ul.jobsearch-ResultsList', timeout=10)
        except Exception:
            pass
            
        from bs4 import BeautifulSoup
        html_content = driver.get_page_source()
        soup = BeautifulSoup(html_content, 'html.parser')
        
        content_text = ""
        # Extract job cards
        job_cards = soup.find_all('div', class_='job_seen_beacon')
        for card in job_cards:
            a_tag = card.find('a', id=lambda x: x and x.startswith('job_'))
            if a_tag:
                href = a_tag.get('href', '')
                if href.startswith('/'):
                    href = "https://www.indeed.com" + href
                if is_job_seen(href):
                    logging.debug(f"    ⏭️ Skipping known job (cached): {href}")
                    continue
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
                    if is_job_seen(href):
                        logging.debug(f"    ⏭️ Skipping known job (cached): {href}")
                        continue
                    text = a.get_text(separator=" ", strip=True)
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
