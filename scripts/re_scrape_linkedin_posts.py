import os
import sys
import json
import sqlite3
import logging
import time

# Ensure project root is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from scrapers.playwright_scraper import LinkedInSession
from core.apply_classifier import classify_and_extract
from core.job_utils import normalize_site, normalize_company, score_job_dict
from core.scorer import load_latest_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("re_scrape_posts")

DB_PATH = os.path.join(BASE_DIR, "output", "jobs_state.db")


def re_scrape_and_enrich():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Query all target jobs: whatsapp_export, lnkd, or linkedin post URLs
    query = """
        SELECT job_id, title, company, location, job_url, job_type, date_posted, 
               site, relevance_score, description, status, is_applied, apply_type, apply_payload
        FROM jobs
        WHERE site IN ('whatsapp_export', 'lnkd')
           OR job_url LIKE '%linkedin.com/posts/%'
           OR job_url LIKE '%lnkd.in%'
           OR (site = 'linkedin_posts' AND LENGTH(description) < 600)
    """
    rows = cursor.execute(query).fetchall()
    logger.info(f"Found {len(rows)} target jobs to review/re-scrape.")

    if not rows:
        print("No target jobs found to re-scrape.")
        return

    config = load_latest_config()
    updated_count = 0
    stats = {"email": 0, "form": 0, "whatsapp": 0, "social_post": 0, "other": 0}

    with LinkedInSession() as page:
        if not page:
            logger.error("Failed to start Playwright LinkedIn session.")
            return

        for idx, row in enumerate(rows, 1):
            job_id = row["job_id"]
            title = row["title"]
            url = row["job_url"] or ""
            current_site = row["site"]
            current_desc = row["description"] or ""
            current_company = row["company"] or "Unknown"

            norm_site = normalize_site(current_site, url)
            new_desc = current_desc
            logger.info(f"[{idx}/{len(rows)}] Processing: {title[:40]} | Current Site: {current_site} -> {norm_site}")

            # If description is short or from whatsapp_export, attempt to fetch from LinkedIn
            need_fetch = (len(current_desc) < 600 or current_site == "whatsapp_export") and url.startswith("http")
            
            if need_fetch:
                try:
                    logger.info(f"  Fetching full post text from {url[:70]}...")
                    page.goto(url, wait_until="domcontentloaded", timeout=16000)
                    page.wait_for_timeout(2000)

                    # Expand see-more buttons
                    page.evaluate("""() => {
                        document.querySelectorAll('button[aria-label*="more" i], .feed-shared-inline-show-more-text__see-more-less-toggle, button.see-more, .feed-shared-see-more-less-toggle').forEach(b => {
                            try { b.click(); } catch(e) {}
                        });
                    }""")
                    page.wait_for_timeout(500)

                    extracted = page.evaluate("""() => {
                        let expanded = document.querySelector('[id*="expanded"], [id*="FeedType"]');
                        if (expanded && expanded.innerText.trim().length > 50) {
                            return expanded.innerText.trim();
                        }
                        let article = document.querySelector('article, main, .feed-shared-update-v2');
                        if (article) {
                            let pTags = Array.from(article.querySelectorAll('p, span')).filter(el => (el.innerText || '').trim().length > 80);
                            if (pTags.length > 0) {
                                return pTags[0].innerText.trim();
                            }
                            return article.innerText.trim();
                        }
                        return document.body.innerText.trim();
                    }""")

                    if extracted and len(extracted) > 100:
                        # Avoid overriding with generic login page text if logged out
                        if "sign in" not in extracted.lower()[:150] or "we're hiring" in extracted.lower():
                            new_desc = extracted
                            logger.info(f"  Successfully extracted {len(new_desc)} chars of post text.")
                        else:
                            logger.warning("  Extracted text appears to be login wall, keeping original snippet.")
                    else:
                        logger.warning("  Extracted text was too short, keeping original snippet.")
                except Exception as e:
                    logger.warning(f"  Failed to fetch post {url}: {e}")

            # Reclassify with classify_and_extract
            job_dict = {
                "job_id": job_id,
                "title": title,
                "company": current_company,
                "location": row["location"],
                "job_url": url,
                "job_type": row["job_type"],
                "date_posted": row["date_posted"],
                "site": norm_site,
                "description": new_desc,
                "is_remote": False,
                "is_scholarship": False,
                "status": row["status"],
                "is_applied": row["is_applied"]
            }

            classification = classify_and_extract(job_dict)
            apply_type = classification.get("apply_type", "social_post")
            apply_payload_json = json.dumps(classification.get("apply_payload", {}))

            # Try to enrich company if unknown
            new_company = normalize_company(current_company, new_desc)

            # Re-score
            job_dict["company"] = new_company
            job_dict["description"] = new_desc
            job_dict["site"] = norm_site
            score_job_dict(job_dict, config=config)
            new_score = float(job_dict.get("relevance_score", row["relevance_score"]))

            # Update DB
            cursor.execute("""
                UPDATE jobs
                SET site = ?,
                    description = ?,
                    company = ?,
                    apply_type = ?,
                    apply_payload = ?,
                    relevance_score = ?
                WHERE job_id = ?
            """, (norm_site, new_desc, new_company, apply_type, apply_payload_json, new_score, job_id))
            conn.commit()

            updated_count += 1
            if apply_type in stats:
                stats[apply_type] += 1
            else:
                stats["other"] += 1

            logger.info(f"  -> Site: {norm_site} | Apply Type: {apply_type} | Score: {new_score:.1f}")

    conn.close()
    print("\n" + "=" * 50)
    print(f"Enrichment Complete! Total records updated: {updated_count}")
    print(f"Breakdown by Apply Type:")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print("=" * 50)


if __name__ == "__main__":
    re_scrape_and_enrich()
