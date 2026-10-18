import os
import sys
import pandas as pd
import datetime
import logging
import re

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

def fetch_indeed_full_description(*args, **kwargs):
    """Stub kept for backwards-compatibility; descriptions are extracted directly via JobSpy."""
    return ""

def scrape_indeed(search_term, location, results_wanted=15, hours_old=None, *args, **kwargs):
    jobs = []
    
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
    except Exception as spy_err:
        logging.error(f"⚠️ Indeed (JobSpy) scraper error: {spy_err}")

    return pd.DataFrame(jobs)

if __name__ == "__main__":
    if sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
    print("Testing Indeed Scraper...")
    df = scrape_indeed("data scientist", "egypt", 5)
    print(df.head())
