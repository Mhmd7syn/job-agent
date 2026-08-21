import sys
import urllib.parse
import pandas as pd
import datetime
import logging
import random

from core.llm_parser import extract_feed_posts_with_ai
from core.database import is_job_seen

def fetch_bayt_full_description(job_url, driver=None):
    """Fetches the complete full job description and requirements from a Bayt job page."""
    if not job_url or 'bayt.com/en/' not in job_url:
        return ""
    try:
        import requests
        from bs4 import BeautifulSoup
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        resp = requests.get(job_url, headers=headers, timeout=6)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.content, 'html.parser')
            desc_div = soup.find('div', class_=lambda c: c and any(k in str(c) for k in ['card-content', 't-break', 'job-description', 'is-space-bottom-large']))
            if desc_div:
                text = desc_div.get_text(separator='\n', strip=True)
                if len(text) > 80:
                    return text
    except Exception as e:
        logging.debug(f"Bayt requests fetch failed for {job_url}: {e}")

    if driver:
        try:
            driver.uc_open_with_reconnect(job_url, 3)
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(driver.get_page_source(), 'html.parser')
            desc_div = soup.find('div', class_=lambda c: c and any(k in str(c) for k in ['card-content', 't-break', 'job-description']))
            if desc_div:
                return desc_div.get_text(separator='\n', strip=True)
        except Exception as e:
            logging.debug(f"Bayt driver fallback failed for {job_url}: {e}")

    return ""

def scrape_bayt(search_term, location, results_wanted=15, hours_old=None, driver=None):
    jobs = []
    query = search_term
    
    loc_path = "egypt" if "egypt" in location.lower() else "international"
    url = f"https://www.bayt.com/en/{loc_path}/jobs/?q={urllib.parse.quote(query)}&options[sort][]=d"
    if hours_old:
        days = hours_old / 24
        if days <= 1:
            interval = 3
        elif days <= 7:
            interval = 2
        else:
            interval = 1
        url += f"&filters[jb_last_modification_date_interval][]={interval}"
    
    if driver is None:
        logging.error("Bayt scraper requires a SeleniumBase driver.")
        return pd.DataFrame()

    try:
        driver.uc_open_with_reconnect(url, 4)
        try:
            driver.uc_gui_click_captcha()
        except Exception:
            pass
        
        try:
            driver.wait_for_element('li.has-pointer-d', timeout=10)
        except Exception:
            pass

        from bs4 import BeautifulSoup
        html_content = driver.get_page_source()
        soup = BeautifulSoup(html_content, 'html.parser')
        
        content_text = ""
        # Extract job cards
        job_cards = soup.find_all('li', class_='has-pointer-d')
        for card in job_cards:
            title_elem = card.find('h2')
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
                    card_desc = job.get('description', '')
                    full_desc = fetch_bayt_full_description(job_url, driver=driver) if job_url and job_url != url else ""
                    final_desc = full_desc if full_desc and len(full_desc) > len(card_desc) else card_desc

                    jobs.append({
                        'title': job.get('title', 'Unknown'),
                        'company': job.get('company', 'Unknown'),
                        'location': job.get('location', location),
                        'job_url': job_url,
                        'job_type': 'Not specified',
                        'description': final_desc,
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
