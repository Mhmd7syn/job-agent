import os
import sys
import urllib.parse
import pandas as pd
import datetime
import logging
import re
from bs4 import BeautifulSoup

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config import GLASSDOOR_LOC_ID
from core.database import is_job_seen

def fetch_glassdoor_full_description(driver, job_url):
    """Fetches the complete full job description and requirements from a Glassdoor job page."""
    if not driver or not job_url or 'glassdoor.com/Job/jobs.htm' in job_url:
        return ""
    try:
        from curl_cffi import requests as c_requests
        resp = c_requests.get(job_url, impersonate="chrome120", timeout=5)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.content, 'html.parser')
            desc_div = soup.find('div', class_=lambda c: c and any(k in str(c) for k in ['jobDescriptionContent', 'JobDetails_jobDescription', 'desc']))
            if desc_div:
                text = desc_div.get_text(separator='\n', strip=True)
                if len(text) > 80:
                    return text
    except Exception:
        pass
    return ""

def scrape_glassdoor(search_term, location, results_wanted=15, hours_old=None, driver=None):
    jobs = []
    
    url = f"https://www.glassdoor.com/Job/jobs.htm?sc.keyword={urllib.parse.quote(search_term)}&locT=N&locId={GLASSDOOR_LOC_ID}&locKeyword={urllib.parse.quote(location)}&sortBy=date_desc"
    if hours_old:
        days = int(hours_old / 24)
        if days > 0:
            url += f"&fromAge={days}"
    
    if driver is None:
        return pd.DataFrame()
        
    try:
        driver.uc_open_with_reconnect(url, 4)
        try:
            driver.uc_gui_click_captcha()
        except Exception:
            pass
        
        try:
            driver.wait_for_element('li', timeout=8)
        except Exception:
            pass

        html_content = driver.get_page_source()
        soup = BeautifulSoup(html_content, 'html.parser')
        
        job_cards = soup.find_all('li')
        cutoff = (datetime.datetime.now() - datetime.timedelta(hours=hours_old)).date() if hours_old else None

        for card in job_cards:
            if len(jobs) >= results_wanted:
                break

            a_tag = card.find('a', href=True)
            if not a_tag:
                continue

            href = a_tag['href']
            if not ('job-listing' in href or '/partner/' in href):
                continue

            if href.startswith('/'):
                href = "https://www.glassdoor.com" + href

            if is_job_seen(href):
                continue

            title_elem = card.find(['a', 'span'], class_=lambda c: c and any(k in str(c) for k in ['JobTitle', 'job-title', 'jobTitle'])) or a_tag
            title = title_elem.text.strip() if title_elem else ""
            if not title or len(title) < 2:
                continue

            comp_elem = card.find(['span', 'div', 'p'], class_=lambda c: c and any(k in str(c) for k in ['EmployerName', 'employer', 'company']))
            company = comp_elem.text.strip() if comp_elem else "Unknown"

            loc_elem = card.find(['div', 'span'], class_=lambda c: c and any(k in str(c) for k in ['location', 'Location', 'loc']))
            loc_val = loc_elem.text.strip() if loc_elem else location

            card_desc = card.get_text(separator=' ', strip=True)

            jobs.append({
                'title': title,
                'company': company,
                'location': loc_val,
                'job_url': href,
                'job_type': 'Not specified',
                'description': card_desc,
                'is_remote': 'remote' in search_term.lower() or 'remote' in str(loc_val).lower(),
                'site': 'glassdoor',
                'date_posted': datetime.datetime.now().date()
            })
            
    except Exception as e:
        logging.error(f"⚠️ Glassdoor Scraper Error: {e}")
            
    return pd.DataFrame(jobs)

if __name__ == "__main__":
    if sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
    print("Testing Glassdoor Scraper...")
    df = scrape_glassdoor("data scientist", "egypt", 5)
    print(df.head())
