import os
import sys
import sqlite3
import json
import logging
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
    sys.stderr.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

from scrapers.glassdoor_scraper import fetch_glassdoor_job_details, clean_glassdoor_company
from scrapers.selenium_scraper import SeleniumSession
from core.apply_classifier import classify_and_extract

def rescrape_glassdoor_jobs():
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "jobs_state.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Get Glassdoor jobs that need checking (or all Glassdoor jobs)
    cur.execute('''
        SELECT job_id, job_url, title, company, description, apply_type, is_easy_apply, apply_url
        FROM jobs
        WHERE site = 'glassdoor'
        ORDER BY CASE WHEN apply_url IS NOT NULL THEN 1 ELSE 0 END, rowid ASC
    ''')
    jobs = [dict(r) for r in cur.fetchall()]
    conn.close()

    logging.info(f"Found {len(jobs)} Glassdoor jobs to inspect and update.")
    if not jobs:
        print("No Glassdoor jobs found in database.")
        return

    updated_count = 0
    easy_apply_count = 0
    employer_site_count = 0

    with SeleniumSession() as driver:
        for idx, job in enumerate(jobs, 1):
            job_id = job['job_id']
            url = job['job_url']
            title = job['title']
            company = job['company']
            old_desc = job.get('description') or ''

            # Skip if already verified Easy Apply with partner link
            if job.get('is_easy_apply') == 1 and job.get('apply_url'):
                logging.info(f"[{idx}/{len(jobs)}] Skipping already verified Easy Apply: '{title}' @ '{company}'")
                easy_apply_count += 1
                updated_count += 1
                continue

            # Skip if already verified Workday ATS
            if job.get('apply_type') == 'platform' and job.get('apply_url'):
                logging.info(f"[{idx}/{len(jobs)}] Skipping already verified ATS platform: '{title}' @ '{company}'")
                employer_site_count += 1
                updated_count += 1
                continue

            logging.info(f"[{idx}/{len(jobs)}] Fetching Glassdoor details for '{title}' @ '{company}'...")
            sys.stdout.flush()
            try:
                details = fetch_glassdoor_job_details(driver, url)
                is_ea = details.get('is_easy_apply')
                apply_url = details.get('apply_url') or job.get('apply_url') or ''
                new_desc = details.get('description') or old_desc
                new_comp = clean_glassdoor_company(details.get('company') or company)

                # Prepare updated dict for classifier
                updated_job_dict = {
                    'job_id': job_id,
                    'title': title,
                    'company': new_comp,
                    'site': 'glassdoor',
                    'job_url': url,
                    'apply_url': apply_url,
                    'description': new_desc,
                    'is_easy_apply': 1 if is_ea else 0 if is_ea is not None else 0
                }

                cls = classify_and_extract(updated_job_dict)
                apply_type = cls.get('apply_type', 'manual')
                apply_payload = json.dumps(cls.get('apply_payload', {}), ensure_ascii=False)
                is_ea_val = 1 if is_ea else 0

                # Write directly to database
                conn = sqlite3.connect(db_path)
                c = conn.cursor()
                c.execute('''
                    UPDATE jobs
                    SET is_easy_apply = ?,
                        apply_url = ?,
                        apply_type = ?,
                        apply_payload = ?,
                        company = ?,
                        description = ?
                    WHERE job_id = ?
                ''', (is_ea_val, apply_url, apply_type, apply_payload, new_comp, new_desc, job_id))
                conn.commit()
                conn.close()

                updated_count += 1
                if is_ea:
                    easy_apply_count += 1
                    logging.info(f"  [EASY APPLY] '{title}' @ '{new_comp}' (ea=1)")
                else:
                    employer_site_count += 1
                    logging.info(f"  [EMPLOYER SITE] '{title}' @ '{new_comp}' (type: {apply_type})")
                sys.stdout.flush()

                time.sleep(1.0)
            except Exception as e:
                logging.error(f"  [ERROR] Processing '{title}': {e}")
                sys.stdout.flush()
                time.sleep(2.0)

    print(f"\nCompleted Glassdoor re-scrape!")
    print(f"Total processed: {updated_count}/{len(jobs)}")
    print(f"Easy Apply jobs: {easy_apply_count}")
    print(f"Employer Site jobs: {employer_site_count}")

if __name__ == '__main__':
    rescrape_glassdoor_jobs()

