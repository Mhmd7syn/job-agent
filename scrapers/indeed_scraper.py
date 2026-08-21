import sys
import urllib.parse
import pandas as pd
import datetime
import logging
import random

from core.llm_parser import extract_feed_posts_with_ai
from core.database import is_job_seen

def fetch_indeed_full_description(driver, job_url):
    """Navigates to an Indeed job page and extracts the complete job description text."""
    if not driver or not job_url:
        return ""
    try:
        driver.uc_open_with_reconnect(job_url, 3)
        try:
            driver.wait_for_element('div#jobDescriptionText, div.jobsearch-JobComponent', timeout=6)
        except Exception:
            pass
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(driver.get_page_source(), 'html.parser')
        desc_div = soup.find('div', id='jobDescriptionText') or soup.find('div', class_=lambda c: c and 'jobsearch-JobComponent' in c)
        if desc_div:
            text = desc_div.get_text(separator='\n', strip=True)
            if len(text) > 80:
                return text
    except Exception as e:
        logging.debug(f"Indeed full description fetch failed for {job_url}: {e}")
    return ""

def scrape_indeed(search_term, location, results_wanted=15, hours_old=None, driver=None):
    jobs = []
    
    # 1. Primary Method: JobSpy (Bypasses Indeed Cloudflare anti-bot blocks and gets full 100% descriptions)
    try:
        from jobspy import scrape_jobs
        country = 'Egypt' if ('egypt' in location.lower() or 'cairo' in location.lower()) else 'USA'
        hours = int(hours_old) if hours_old else 168
        
        logging.info(f"🔍 Searching Indeed via JobSpy: '{search_term}' in '{location}'")
        spy_df = scrape_jobs(
            site_name=["indeed"],
            search_term=search_term,
            location=location,
            results_wanted=results_wanted,
            hours_old=hours,
            country_indeed=country
        )
        
        if spy_df is not None and not spy_df.empty:
            for _, row in spy_df.iterrows():
                job_url = str(row.get('job_url', ''))
                if not job_url or is_job_seen(job_url):
                    continue
                
                title = str(row.get('title', 'Unknown'))
                company = str(row.get('company', 'Unknown'))
                desc = str(row.get('description', ''))
                job_type = str(row.get('job_type', 'Not specified'))
                loc_val = str(row.get('location', location))
                date_val = row.get('date_posted') or datetime.datetime.now().date()
                
                jobs.append({
                    'title': title,
                    'company': company,
                    'location': loc_val,
                    'job_url': job_url,
                    'job_type': job_type,
                    'description': desc,
                    'is_remote': 'remote' in search_term.lower() or 'remote' in loc_val.lower(),
                    'site': 'indeed',
                    'date_posted': date_val
                })
            
            if jobs:
                logging.info(f"✅ Indeed (JobSpy): Extracted {len(jobs)} jobs with full descriptions.")
                return pd.DataFrame(jobs)
    except Exception as spy_err:
        logging.warning(f"⚠️ JobSpy Indeed extraction issue: {spy_err}. Falling back to SeleniumBase...")

    # 2. Fallback Method: SeleniumBase Browser
    url = f"https://www.indeed.com/jobs?q={urllib.parse.quote(search_term)}&l={urllib.parse.quote(location)}&sort=date"
    if hours_old:
        days = int(hours_old / 24)
        if days > 0:
            url += f"&fromage={days}"
    
    if driver is None:
        return pd.DataFrame(jobs)
        
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
                    full_desc = fetch_indeed_full_description(driver, job_url) if job_url and job_url != url else ""
                    final_desc = full_desc if full_desc and len(full_desc) > len(card_desc) else card_desc

                    jobs.append({
                        'title': job.get('title', 'Unknown'),
                        'company': job.get('company', 'Unknown'),
                        'location': job.get('location', location),
                        'job_url': job_url,
                        'job_type': job.get('job_type', 'Not specified'),
                        'description': final_desc,
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
