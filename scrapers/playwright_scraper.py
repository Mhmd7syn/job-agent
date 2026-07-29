import os
import time
import json
import re
import urllib.parse
import random
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
import sys
import logging
import pandas as pd
from core.llm_parser import extract_job_page_with_ai, extract_feed_posts_with_ai, extract_json_ld
from core.database import is_job_seen

LOGIN_FAILED = False

if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # Project root (parent of scrapers/)
env_path = os.path.join(BASE_DIR, '.env')
USER_DATA_DIR = os.path.join(BASE_DIR, "playwright_profile")
load_dotenv(dotenv_path=env_path)


def launch_persistent_browser(playwright_instance, user_data_dir, headless=True, **kwargs):
    """Launch browser persistently using local Google Chrome or Microsoft Edge to save disk space and bypass anti-bot checks."""
    channels = ["chrome", "msedge", None]
    last_exception = None
    
    default_args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-infobars",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-quic",
        "--ignore-certificate-errors",
    ]
    if not headless:
        default_args.append("--start-maximized")
    else:
        default_args.append("--window-size=1920,1080")
        
    custom_args = kwargs.pop("args", [])
    combined_args = list(set(default_args + custom_args))
    
    ignore_default_args = kwargs.pop("ignore_default_args", ["--enable-automation", "--enable-blink-features=IdleDetection"])
    viewport = kwargs.pop("viewport", None)

    chrome_bin = os.path.join(BASE_DIR, "chrome-win64", "chrome.exe")
    
    launch_args = {
        "user_data_dir": user_data_dir,
        "headless": headless,
        "args": combined_args,
        "ignore_default_args": ignore_default_args,
        "viewport": viewport,
        **kwargs
    }
    
    if os.path.exists(chrome_bin):
        launch_args["executable_path"] = chrome_bin
    else:
        launch_args["channel"] = "chrome"

    return playwright_instance.chromium.launch_persistent_context(**launch_args)
def auto_login_if_needed(page):
    global LOGIN_FAILED
    if LOGIN_FAILED:
        logging.warning("⚠️ Skipping auto-login attempt because a previous attempt failed in this session.")
        return

    email = os.getenv("LINKEDIN_EMAIL")
    password = os.getenv("LINKEDIN_PASSWORD")

    if "login" in page.url or "authwall" in page.url or page.query_selector('input[id="username"]') or page.query_selector('input[id="session_key"]'):
        if email and password:
            logging.info("🔐 Playwright is logged out. Attempting auto-login...")
            try:
                page.goto("https://www.linkedin.com/login")
                page.wait_for_load_state("domcontentloaded")
                page.wait_for_timeout(random.randint(2000, 4000))

                if page.query_selector('input[id="username"]'):
                    page.fill('input[id="username"]', email)
                    page.fill('input[id="password"]', password)
                    page.click('button[type="submit"]')
                elif page.query_selector('input[id="session_key"]'):
                    page.fill('input[id="session_key"]', email)
                    page.fill('input[id="session_password"]', password)
                    try:
                        page.click('button[data-id="sign-in-form__submit-btn"]', timeout=3000)
                    except:
                        page.click('button[type="submit"]', timeout=3000)

                try:
                    page.wait_for_url(lambda url: "login" not in url and "checkpoint" not in url and "challenge" not in url, timeout=10000)
                except:
                    pass
                page.wait_for_timeout(random.randint(3000, 5000))

                if "challenge" in page.url or "checkpoint" in page.url:
                    logging.warning("⚠️ LinkedIn is asking for a security check. Please run linkedin_login.py manually.")
                    LOGIN_FAILED = True
                elif "login" in page.url or "authwall" in page.url:
                    logging.error("❌ Auto-login failed (possibly due to headless mode). Please run linkedin_login.py manually.")
                    LOGIN_FAILED = True
                else:
                    logging.info("✅ Auto-login submitted and seems successful!")
            except Exception as e:
                logging.error(f"⚠️ Auto-login error: {e}")
                LOGIN_FAILED = True
        else:
            logging.error("❌ Playwright is logged out but LINKEDIN_EMAIL/LINKEDIN_PASSWORD not in .env")


class LinkedInSession:
    """Reusable Playwright browser session for LinkedIn.

    Creates ONE browser context for the entire run and reuses it across all
    search terms, eliminating the overhead of launching a new browser per term.

    Usage in job_agent.py:
        with LinkedInSession() as li_page:
            for term in SEARCH_TERMS:
                scrape_linkedin_jobs_playwright(term, loc, page=li_page)
    """

    def __init__(self):
        self._pw = None
        self._context = None
        self.page = None

    def __enter__(self):
        try:
            self._pw = sync_playwright().start()
            self._context = launch_persistent_browser(
                self._pw,
                user_data_dir=USER_DATA_DIR,
                headless=True
            )
            self._context.grant_permissions(['clipboard-read', 'clipboard-write'])
            self.page = self._context.pages[0] if self._context.pages else self._context.new_page()
            Stealth().apply_stealth_sync(self.page)
            # Warm-up: confirm login state once for the whole session
            self.page.goto('https://www.linkedin.com/feed/', wait_until='domcontentloaded')
            auto_login_if_needed(self.page)
        except Exception as e:
            logging.error(f"⚠️ Failed to create LinkedIn session: {e}")
            self._cleanup()
        return self.page

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._cleanup()

    def _cleanup(self):
        try:
            if self._context:
                self._context.close()
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._context = None
        self._pw = None
        self.page = None


# ---------------------------------------------------------------------------
# Core scraping logic — operates on an existing page object
# ---------------------------------------------------------------------------

_POST_EXTRACTOR_JS = r'''() => {
    let result = "";
    let isAuthorLink = (href) => href && (href.includes('/in/') || href.includes('/company/'));
    let menuBtns = document.querySelectorAll(
        'button[aria-label*="Control Menu"], button[aria-label*="control menu" i], ' +
        '.feed-shared-control-menu__trigger, .artdeco-dropdown__trigger'
    );
    let posts = Array.from(menuBtns).map(btn =>
        btn.closest('li.reusable-search__result-container') ||
        btn.closest('.feed-shared-update-v2') ||
        btn.closest('.search-entity') ||
        btn.closest('li') ||
        btn.parentElement?.parentElement?.parentElement
    ).filter(Boolean);
    posts = Array.from(new Set(posts));

    if (posts.length === 0) { return document.body.innerText; }

    for (let post of posts) {
        let postUrl = "";
        for (let a of post.querySelectorAll('a')) {
            if (a.href) {
                if (a.href.includes('/feed/update/urn:li:') || a.href.includes('/posts/') || a.href.includes('-activity-')) {
                    postUrl = a.href.split('?')[0];
                    break;
                }
            }
        }
        if (!postUrl) {
            let dataUrn = post.getAttribute('data-urn') || post.querySelector('[data-urn]')?.getAttribute('data-urn');
            if (dataUrn) {
                let match = dataUrn.match(/activity:(\d+)/) || dataUrn.match(/ugcPost:(\d+)/) || dataUrn.match(/share:(\d+)/);
                if (match) {
                    postUrl = "https://www.linkedin.com/feed/update/urn:li:activity:" + match[1];
                }
            }
        }
        if (!postUrl) {
            let outerMatch = post.outerHTML.match(/(?:urn:li:)?(?:activity|ugcPost|share)[:-](\d{18,20})/);
            if (outerMatch) {
                postUrl = "https://www.linkedin.com/feed/update/urn:li:activity:" + outerMatch[1];
            }
        }
        
        let text = post.innerText;
        if (text && text.trim().length > 20) {
            if (postUrl) {
                result += "Post URL: " + postUrl + "\\n";
            }
            result += "Post Text:\\n" + text + "\\n\\n---END OF POST---\\n\\n";
        }
    }
    return result || document.body.innerText;
}'''

_JOB_LINK_EXTRACTOR_JS = '''() => {
    const anchors = Array.from(document.querySelectorAll('a'));
    const jobLinks = new Set();
    anchors.forEach(a => {
        if (a.href && (a.href.includes('/jobs/view/') || a.href.includes('currentJobId='))) {
            let cleanUrl = a.href.split('?')[0];
            if (a.href.includes('currentJobId=')) {
                try {
                    const params = new URLSearchParams(new URL(a.href).search);
                    if (params.get('currentJobId')) {
                        cleanUrl = 'https://www.linkedin.com/jobs/view/' + params.get('currentJobId');
                    }
                } catch(e) {}
            }
            jobLinks.add(cleanUrl);
        }
    });
    return Array.from(jobLinks);
}'''


def _do_scrape_linkedin_posts(page, keyword):
    """Post-scraping logic using an existing page object."""
    try:
        encoded_keyword = urllib.parse.quote(keyword)
        search_url = (
            f"https://www.linkedin.com/search/results/content/"
            f"?keywords={encoded_keyword}&origin=GLOBAL_SEARCH_HEADER&sortBy=%22date_posted%22"
        )
        page.goto(search_url, wait_until='domcontentloaded')

        # Scroll to load posts — use wait_for_timeout instead of time.sleep
        for _ in range(3):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1500)

        return page.evaluate(_POST_EXTRACTOR_JS)
    except Exception as e:
        logging.error(f"⚠️ Error during LinkedIn post scraping: {e}")
        return ""


def _do_scrape_linkedin_jobs(page, term, location, results_wanted=5, hours_old=None):
    """Job-scraping logic using an existing page object."""
    import datetime
    jobs = []

    encoded_term = urllib.parse.quote(term)
    encoded_loc = urllib.parse.quote(location)
    url = f"https://www.linkedin.com/jobs/search/?keywords={encoded_term}&location={encoded_loc}&sortBy=DD"
    if hours_old:
        url += f"&f_TPR=r{hours_old * 3600}"

    logging.info(f"🔍 Searching LinkedIn Jobs (Playwright): {term} in {location}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=40000)
        page.wait_for_timeout(random.randint(2000, 4000))

        auto_login_if_needed(page)

        if "login" in page.url or "authwall" in page.url:
            page.goto(url, wait_until="domcontentloaded", timeout=40000)
            page.wait_for_timeout(random.randint(2000, 4000))

        # Scroll to load job list
        for _ in range(3):
            page.mouse.wheel(0, 1000)
            page.wait_for_timeout(700)

        links = page.evaluate(_JOB_LINK_EXTRACTOR_JS)
        # Pre-AI deduplication: skip URLs already in DB before navigating
        new_links = [url for url in links if not is_job_seen(url)]
        skipped = len(links) - len(new_links)
        if skipped:
            logging.info(f"    ⏭️ Skipping {skipped} already-known job(s) (dedup cache)")
        links = new_links[:results_wanted]

        for job_url in links:
            try:
                for attempt in range(2):
                    try:
                        page.goto(job_url, wait_until="domcontentloaded", timeout=25000)
                        page.wait_for_timeout(random.randint(1500, 3000))
                        break
                    except Exception as page_e:
                        if attempt == 0:
                            logging.warning(f"    (Retrying job load: {str(page_e).splitlines()[0][:50]}...)")
                            page.wait_for_timeout(random.randint(3000, 5000))
                        else:
                            raise page_e

                see_more_btn = (
                    page.query_selector('.jobs-description__footer-button') or
                    page.query_selector('button[aria-label="Click to see more description"]')
                )
                if see_more_btn:
                    try:
                        see_more_btn.click(timeout=3000)
                        page.wait_for_timeout(700)
                    except:
                        pass

                page_html = page.evaluate("document.documentElement.innerHTML")
                # Try JSON-LD zero-token fast-path first
                ai_data = extract_json_ld(page_html)
                if ai_data:
                    logging.debug(f"    ⚡ JSON-LD fast-path used for {job_url}")
                else:
                    page_text = page.evaluate("document.body.innerText")
                    ai_data = extract_job_page_with_ai(page_text[:10000])

                if ai_data and not ai_data.get("error"):
                    title = ai_data.get('title', 'Unknown')
                    if title not in ("Unknown", "Not specified"):
                        jobs.append({
                            'title': title,
                            'company': ai_data.get('company', 'Unknown'),
                            'location': ai_data.get('location', location),
                            'job_url': job_url,
                            'description': ai_data.get('description', ''),
                            'site': 'linkedin',
                            'is_remote': 'remote' in str(ai_data.get('location', '')).lower() or 'remote' in location.lower(),
                            'date_posted': ai_data.get('date_posted') or datetime.date.today(),
                            'job_type': 'Not specified'
                        })
                else:
                    logging.warning(f"⚠️ AI Parsing failed for {job_url}: {ai_data.get('error') if ai_data else 'Unknown'}")

            except Exception as e:
                logging.error(f"⚠️ Failed to parse job {job_url}: {e}")

    except Exception as e:
        err_msg = str(e)
        if "ERR_CONNECTION_ABORTED" in err_msg or "ERR_CONNECTION_CLOSED" in err_msg:
            logging.error(f"⚠️ LinkedIn Search failed for '{term}' - Connection aborted. This usually means LinkedIn blocked the headless browser. Try updating login session/cookies. Error: {e}")
        else:
            logging.error(f"⚠️ LinkedIn Search failed for {term}: {e}")

    return pd.DataFrame(jobs)


# ---------------------------------------------------------------------------
# Public API — accept optional `page` for session reuse
# ---------------------------------------------------------------------------

def scrape_linkedin_posts_playwright(keyword, page=None):
    """Scrape LinkedIn post search results.

    Pass `page` from a LinkedInSession to reuse the browser.
    Falls back to creating its own browser if called standalone.
    """
    if page is not None:
        return _do_scrape_linkedin_posts(page, keyword)

    # Standalone fallback
    with sync_playwright() as p:
        context = launch_persistent_browser(p, user_data_dir=USER_DATA_DIR, headless=True)
        context.grant_permissions(['clipboard-read', 'clipboard-write'])
        pg = context.pages[0] if context.pages else context.new_page()
        Stealth().apply_stealth_sync(pg)
        try:
            pg.goto('https://www.linkedin.com/feed/', wait_until='domcontentloaded')
            auto_login_if_needed(pg)
            return _do_scrape_linkedin_posts(pg, keyword)
        finally:
            context.close()


def scrape_linkedin_jobs_playwright(term, location, results_wanted=5, hours_old=None, page=None):
    """Scrape LinkedIn Jobs.

    Pass `page` from a LinkedInSession to reuse the browser.
    Falls back to creating its own browser if called standalone.
    """
    if page is not None:
        return _do_scrape_linkedin_jobs(page, term, location, results_wanted, hours_old)

    # Standalone fallback
    with sync_playwright() as p:
        context = launch_persistent_browser(p, user_data_dir=USER_DATA_DIR, headless=True)
        pg = context.pages[0] if context.pages else context.new_page()
        Stealth().apply_stealth_sync(pg)
        try:
            return _do_scrape_linkedin_jobs(pg, term, location, results_wanted, hours_old)
        finally:
            context.close()


def get_posts_as_dataframe(term, loc, page=None):
    """Return LinkedIn post jobs as a DataFrame.

    Pass `page` from a LinkedInSession to reuse the browser.
    """
    from datetime import date

    keyword = f"hiring {term} {loc}"
    feed_text = scrape_linkedin_posts_playwright(keyword, page=page)

    if not feed_text or len(feed_text) < 50:
        return pd.DataFrame()

    valid_jobs = []
    ai_data = extract_feed_posts_with_ai(feed_text[:15000])

    if ai_data and not ai_data.get("error"):
        for job in ai_data.get("jobs", []):
            if job.get("is_job"):
                valid_jobs.append({
                    'title': job.get('title', 'Unknown'),
                    'company': job.get('company', 'Unknown'),
                    'location': job.get('location', loc),
                    'job_url': job.get('job_url') or f"https://www.linkedin.com/search/results/content/?keywords={keyword}",
                    'description': job.get('description', ''),
                    'is_remote': 'remote' in str(job.get('location', '')).lower(),
                    'date_posted': job.get('date_posted') or date.today(),
                    'job_type': 'Not specified',
                    'site': 'linkedin_posts'
                })
    else:
        logging.warning(f"⚠️ Error from Gemini: {ai_data.get('error') if ai_data else 'Unknown'}")

    return pd.DataFrame(valid_jobs) if valid_jobs else pd.DataFrame()


if __name__ == "__main__":
    print("--- Playwright LinkedIn Post Scraper ---")
    if not os.getenv("GEMINI_API_KEY"):
        print("⚠️ Warning: GEMINI_API_KEY not found in .env. AI Extraction will be disabled.\n")

    with LinkedInSession() as li_page:
        feed_text = _do_scrape_linkedin_posts(li_page, "hiring data scientist egypt")

    if feed_text:
        print(f"\n--- Processing Feed with Gemini AI ---")
        print(f"Extracted {len(feed_text)} characters of feed text.")
        ai_data = extract_feed_posts_with_ai(feed_text[:15000])
        print(json.dumps(ai_data, indent=2, ensure_ascii=False))
    else:
        print("\nNo posts were found. Check your cookie or search terms.")
