import sqlite3
import os
import sys
import logging
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from scrapers.wuzzuf_scraper import fetch_wuzzuf_full_description
from scrapers.tanqeeb_scraper import fetch_tanqeeb_job_details
from scrapers.glassdoor_scraper import fetch_glassdoor_full_description
from scrapers.indeed_scraper import fetch_indeed_full_description, clean_indeed_company
from core.apply_classifier import classify_and_extract

def rescrape_existing_short_jobs():
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "jobs_state.db")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute('''
        SELECT job_url, site, title, company, description
        FROM jobs
        WHERE length(description) < 500 AND site IN ('wuzzuf', 'tanqeeb', 'glassdoor', 'indeed')
    ''')
    rows = cur.fetchall()
    logging.info(f"Found {len(rows)} existing jobs with short descriptions to re-scrape.")

    if not rows:
        print("All jobs already have full descriptions!")
        return

    # 1. First, re-scrape fast HTTP jobs (Wuzzuf & Tanqeeb)
    fast_http_jobs = [r for r in rows if r[1] in ('wuzzuf', 'tanqeeb')]
    updated_count = 0

    for url, site, title, company, old_desc in fast_http_jobs:
        logging.info(f"Re-scraping [{site}] '{title}' @ '{company}' via fast HTTP...")
        new_desc = ""
        new_comp = company

        if site == 'wuzzuf':
            new_desc = fetch_wuzzuf_full_description(url)
        elif site == 'tanqeeb':
            details = fetch_tanqeeb_job_details(url)
            new_desc = details.get('description', '')
            if details.get('company') and company.lower() in ('unknown', 'linkedin', 'naukri gulf', 'wuzzuf'):
                new_comp = details['company']

        if new_desc and len(new_desc) > len(old_desc):
            cls_res = classify_and_extract({'job_url': url, 'description': new_desc, 'title': title, 'company': new_comp, 'site': site})
            cur.execute('''
                UPDATE jobs
                SET description = ?, company = ?, apply_type = ?, apply_payload = ?
                WHERE job_url = ?
            ''', (new_desc, new_comp, cls_res.get('apply_type', 'job_board'), str(cls_res.get('apply_payload', {})), url))
            conn.commit()
            updated_count += 1
            logging.info(f"  ✅ Updated '{title}' ({len(old_desc)} -> {len(new_desc)} chars)")

    # 2. Re-scrape browser-assisted jobs (Glassdoor & Indeed)
    browser_jobs = [r for r in rows if r[1] in ('glassdoor', 'indeed')]
    if browser_jobs:
        logging.info(f"Launching SeleniumSession for {len(browser_jobs)} browser jobs...")
        try:
            from scrapers.selenium_scraper import SeleniumSession
            with SeleniumSession() as driver:
                for url, site, title, company, old_desc in browser_jobs:
                    logging.info(f"Re-scraping [{site}] '{title}' @ '{company}'...")
                    new_desc = ""
                    new_comp = company

                    if site == 'glassdoor':
                        new_desc = fetch_glassdoor_full_description(url, driver=driver)
                    elif site == 'indeed':
                        new_desc = fetch_indeed_full_description(driver, url)
                        new_comp = clean_indeed_company(company)

                    if new_desc and len(new_desc) > len(old_desc):
                        cls_res = classify_and_extract({'job_url': url, 'description': new_desc, 'title': title, 'company': new_comp, 'site': site})
                        cur.execute('''
                            UPDATE jobs
                            SET description = ?, company = ?, apply_type = ?, apply_payload = ?
                            WHERE job_url = ?
                        ''', (new_desc, new_comp, cls_res.get('apply_type', 'job_board'), str(cls_res.get('apply_payload', {})), url))
                        conn.commit()
                        updated_count += 1
                        logging.info(f"  ✅ Updated '{title}' ({len(old_desc)} -> {len(new_desc)} chars)")
                    else:
                        logging.info(f"  ⚠️ Could not fetch full desc for '{title}'")
        except Exception as e:
            logging.error(f"Browser re-scrape error: {e}")

    conn.close()
    logging.info(f"🎉 Completed! Successfully updated {updated_count}/{len(rows)} jobs with full descriptions.")

if __name__ == '__main__':
    rescrape_existing_short_jobs()
