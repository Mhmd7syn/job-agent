import os
import sys
import urllib.parse
import pandas as pd
import datetime
import logging
import re
from bs4 import BeautifulSoup

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.database import is_job_seen
from core.job_utils import normalize_job_dict

def clean_indeed_company(company: str) -> str:
    """Strips attached employer ratings, stars, and glued location/zip codes from Indeed companies."""
    if not company:
        return "Unknown"
    cleaned = company.strip()
    # Strip rating suffix e.g. "Valeo3.7" or "Company 4.2 ★" or "4.2"
    cleaned = re.sub(r'\s*\d+\.\d+\s*★?$', '', cleaned).strip()
    # Strip glued rating e.g. "Company4.2"
    cleaned = re.sub(r'([A-Za-z]+)\d+\.\d+.*$', r'\1', cleaned).strip()
    # Strip glued location e.g. "CroweTallahassee, FL 32301" or "CroweTallahassee, FL"
    cleaned = re.sub(r'([a-z0-9])([A-Z][a-z]+(?:[\s-][A-Z][a-z]+)*,\s*[A-Z]{2}(?:\s*\d{5})?)', r'\1', cleaned).strip()
    return cleaned or company

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
                company = clean_indeed_company(str(row.get('company', 'Unknown')))
                desc = str(row.get('description', ''))
                job_type = str(row.get('job_type', 'Not specified'))
                loc_val = str(row.get('location', location))
                date_val = row.get('date_posted') or datetime.datetime.now().date()
                
                direct_url = str(row.get('job_url_direct') or '').strip() or None
                is_ea = bool(row.get('is_direct_apply')) if ('is_direct_apply' in row and pd.notna(row.get('is_direct_apply'))) else None

                jobs.append(normalize_job_dict({
                    'title': title,
                    'company': company,
                    'location': loc_val,
                    'job_url': job_url,
                    'job_type': job_type,
                    'description': desc,
                    'is_remote': 'remote' in search_term.lower() or 'remote' in loc_val.lower(),
                    'site': 'indeed',
                    'date_posted': date_val,
                    'apply_url': direct_url,
                    'is_easy_apply': is_ea
                }))
            
            if jobs:
                logging.info(f"✅ Indeed (JobSpy): Extracted {len(jobs)} jobs with full descriptions.")
                return pd.DataFrame(jobs)
    except Exception as spy_err:
        logging.debug(f"JobSpy unavailable: {spy_err}. Using browser fallback.")

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
        
        # Direct BeautifulSoup parsing without LLM
        job_cards = soup.find_all('div', class_='job_seen_beacon')
        if not job_cards:
            job_cards = soup.find_all(['div', 'li'], class_=lambda c: c and any(k in str(c) for k in ['result', 'jobsearch-ResultsTable', 'cardOutline']))

        for card in job_cards:
            if len(jobs) >= results_wanted:
                break
            a_tag = card.find('a', id=lambda x: x and x.startswith('job_')) or card.find('a', href=lambda h: h and ('/rc/clk' in h or 'vjk=' in h or '/viewjob' in h))
            if not a_tag:
                continue

            href = a_tag.get('href', '')
            if href.startswith('/'):
                href = "https://www.indeed.com" + href

            if is_job_seen(href):
                continue

            title = a_tag.text.strip()
            if not title:
                continue

            comp_elem = card.find(['span', 'div'], class_=lambda c: c and any(k in str(c).lower() for k in ['companyname', 'company_location', 'company']))
            raw_company = comp_elem.text.strip() if comp_elem else "Unknown"
            company = clean_indeed_company(raw_company)

            loc_elem = card.find('div', class_=lambda c: c and any(k in str(c).lower() for k in ['companylocation', 'company_location', 'location']))
            loc_val = loc_elem.text.strip() if loc_elem else location

            desc_elem = card.find('div', class_=lambda c: c and any(k in str(c) for k in ['job-snippet', 'underShelfFooter', 'css-9446fg']))
            card_desc = desc_elem.text.strip() if desc_elem else card.get_text(separator=' ', strip=True)

            # Fetch full description if driver is alive
            full_desc = fetch_indeed_full_description(driver, href) if driver else ""
            final_desc = full_desc if full_desc and len(full_desc) > len(card_desc) else card_desc

            jobs.append(normalize_job_dict({
                'title': title,
                'company': company,
                'location': loc_val,
                'job_url': href,
                'job_type': 'Not specified',
                'description': final_desc,
                'is_remote': 'remote' in search_term.lower() or 'remote' in str(loc_val).lower(),
                'site': 'indeed',
                'date_posted': datetime.datetime.now().date()
            }))
            
    except Exception as e:
        logging.error(f"⚠️ Indeed Scraper Error: {e}")
            
    return pd.DataFrame(jobs)

if __name__ == "__main__":
    if sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
    print("Testing Indeed Scraper...")
    df = scrape_indeed("data scientist", "egypt", 5)
    print(df.head())
