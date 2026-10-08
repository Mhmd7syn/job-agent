import sys
import os
import sqlite3
import json
import urllib.parse
import re

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
    sys.stderr.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from core.apply_classifier import classify_and_extract
from playwright.sync_api import sync_playwright
from scrapers.playwright_scraper import launch_persistent_browser, USER_DATA_DIR

DB_PATH = os.path.join(BASE_DIR, "output", "jobs_state.db")

def migrate_and_backfill():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 1. Update McKinsey & Microsoft known jobs right away
    cur.execute("""
        UPDATE jobs
        SET apply_url = 'https://www.mckinsey.com/careers/search-jobs', is_easy_apply = 0
        WHERE company LIKE '%McKinsey%' AND site = 'glassdoor'
    """)
    print("Updated McKinsey job with official careers portal link.", flush=True)

    cur.execute("""
        UPDATE jobs
        SET apply_url = 'https://apply.careers.microsoft.com/careers/job/1970393556984145?utm_source=linkedin&domain=microsoft.com&src=LinkedIn', is_easy_apply = 0
        WHERE title LIKE '%Applied Scientist II%' AND company LIKE '%Microsoft%' AND site = 'linkedin'
    """)
    cur.execute("""
        UPDATE jobs
        SET apply_url = 'https://apply.careers.microsoft.com/careers/job/1970393556984134?utm_source=linkedin&domain=microsoft.com&src=LinkedIn', is_easy_apply = 0
        WHERE title LIKE '%Snr Applied Scientist%' AND company LIKE '%Microsoft%' AND site = 'linkedin'
    """)
    conn.commit()
    print("Updated Microsoft jobs with official careers portal links.", flush=True)

    # 2. Extract apply URLs for all LinkedIn jobs where apply_url is NULL or empty
    linkedin_jobs = cur.execute("""
        SELECT job_id, title, company, job_url, description
        FROM jobs
        WHERE site = 'linkedin' AND (apply_url IS NULL OR apply_url = '')
    """).fetchall()

    print(f"\nExtracting apply links for {len(linkedin_jobs)} LinkedIn jobs via Playwright...", flush=True)
    if linkedin_jobs:
        try:
            with sync_playwright() as p:
                context = launch_persistent_browser(p, user_data_dir=USER_DATA_DIR, headless=True)
                page = context.pages[0] if context.pages else context.new_page()

                for idx, r in enumerate(linkedin_jobs, 1):
                    job_url = r['job_url']
                    title = r['title']
                    comp = r['company']
                    try:
                        page.goto(job_url, wait_until="domcontentloaded", timeout=8000)
                        page.wait_for_timeout(500)
                        res = page.evaluate("""() => {
                            let applyAnchor = document.querySelector('a.jobs-apply-button, a[href*="/safety/go/"], a[aria-label*="Apply to"], a.apply-button');
                            if (applyAnchor && applyAnchor.href) {
                                return { type: 'anchor', href: applyAnchor.href, is_easy: false };
                            }
                            let applyBtn = document.querySelector('button.jobs-apply-button, button[class*="apply"]');
                            if (applyBtn) {
                                let text = applyBtn.innerText.trim().toLowerCase();
                                let dataUrl = applyBtn.getAttribute('data-apply-url');
                                return { type: 'button', href: dataUrl, is_easy: text.includes('easy apply') };
                            }
                            for (let a of document.querySelectorAll('a[href*="/safety/go/"]')) {
                                return { type: 'safety_anchor', href: a.href, is_easy: false };
                            }
                            return null;
                        }""")

                        extracted_url = None
                        is_ea = None
                        if res:
                            href = res.get("href")
                            is_ea = res.get("is_easy", False)
                            if href:
                                if "/safety/go/" in href or "url=" in href:
                                    parsed = urllib.parse.urlparse(href)
                                    params = urllib.parse.parse_qs(parsed.query)
                                    extracted_url = params.get("url", [href])[0]
                                else:
                                    extracted_url = href

                        if extracted_url or is_ea:
                            print(f"[{idx}/{len(linkedin_jobs)}] '{title}' @ '{comp}' -> apply_url: {extracted_url[:70] if extracted_url else 'None'} | easy_apply: {is_ea}", flush=True)
                            cur.execute("""
                                UPDATE jobs
                                SET apply_url = ?, is_easy_apply = ?
                                WHERE job_id = ?
                            """, (extracted_url, 1 if is_ea else 0 if is_ea is not None else None, r['job_id']))
                            conn.commit()
                        else:
                            print(f"[{idx}/{len(linkedin_jobs)}] '{title}' @ '{comp}' -> Native / No external link", flush=True)
                    except Exception as e:
                        print(f"[{idx}/{len(linkedin_jobs)}] Error on '{title}': {e}", flush=True)
                context.close()
        except Exception as e:
            print(f"Playwright error: {e}", flush=True)

    # 3. Clean up legacy truncated ?pos=101 URLs in Glassdoor jobs
    print("\nCleaning up legacy truncated ?pos=101 in Glassdoor jobs...", flush=True)
    gd_jobs = cur.execute("""
        SELECT job_id, title, company, job_url, apply_url, description
        FROM jobs
        WHERE site = 'glassdoor' AND apply_url = 'https://www.glassdoor.com/partner/jobListing.htm?pos=101'
    """).fetchall()

    for r in gd_jobs:
        desc = r['description'] or ''
        career_matches = [
            m.rstrip('.,;)]}>"\'') for m in re.findall(r'https?://[^\s<>"\']+(?:/careers?|/jobs?|/apply|jobdetail|search-jobs)[^\s<>"\']*', desc, re.IGNORECASE)
            if not any(agg in m.lower() for agg in ['glassdoor.', 'indeed.', 'linkedin.', 'wuzzuf.', 'bayt.', 'tanqeeb.', 'facebook.', 'twitter.', 'google.'])
        ]
        new_apply_url = career_matches[0] if career_matches else None
        cur.execute("UPDATE jobs SET apply_url = ? WHERE job_id = ?", (new_apply_url, r['job_id']))
    conn.commit()
    print(f"Cleaned {len(gd_jobs)} Glassdoor jobs with truncated pos=101.", flush=True)

    # 4. Re-classify ALL jobs in the database to ensure apply_type and apply_payload are 100% up-to-date
    print("\nRe-classifying all jobs in the database...", flush=True)
    all_jobs = cur.execute("""
        SELECT job_id, title, company, site, job_url, apply_url, description, is_easy_apply
        FROM jobs
    """).fetchall()

    reclassified_count = 0
    for r in all_jobs:
        job_dict = dict(r)
        cls = classify_and_extract(job_dict)
        apply_type = cls.get("apply_type", "manual")
        apply_payload = json.dumps(cls.get("apply_payload", {}), ensure_ascii=False)

        cur.execute("""
            UPDATE jobs
            SET apply_type = ?, apply_payload = ?
            WHERE job_id = ?
        """, (apply_type, apply_payload, r['job_id']))
        reclassified_count += 1

    conn.commit()
    conn.close()
    print(f"Successfully reclassified all {reclassified_count} jobs in database!", flush=True)

if __name__ == "__main__":
    migrate_and_backfill()
