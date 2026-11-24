import os
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
from core.llm_parser import extract_feed_posts_with_ai, extract_json_ld
from core.database import is_job_seen, is_job_id_seen, refresh_republished_job
from core.job_utils import make_job_id
from scrapers.common import resolve_canonical_apply_url, extract_embedded_apply_url, extract_applicant_count
from core.config import (
    get_chrome_binary_path,
    get_edge_binary_path,
    get_browser_user_data_dir,
    get_browser_launch_kwargs,
)

LOGIN_FAILED = False

if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # Project root (parent of scrapers/)
env_path = os.path.join(BASE_DIR, '.env')
load_dotenv(dotenv_path=env_path)
USER_DATA_DIR = get_browser_user_data_dir()


def launch_persistent_browser(playwright_instance, user_data_dir, headless=True, **kwargs):
    """Launch browser persistently using Microsoft Edge or local Chrome to save disk space and bypass anti-bot checks."""
    default_args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-infobars",
        "--disable-dev-shm-usage",
        "--disable-quic",
        "--ignore-certificate-errors",
        "--disable-features=EncryptedClientHello,UseDnsHttpsSvcbAlpn,DnsOverHttps,msEdgeSingleSignOn,msEdgeAutoSignIn,msImplicitSignIn",
        "--disable-async-dns",
        "--disable-background-networking",
        "--disable-sync",
        "--disable-default-apps",
        "--no-restore-session-state",
        "--disable-session-crashed-bubble",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if not headless:
        default_args.append("--start-maximized")
    else:
        default_args.append("--window-size=1920,1080")
        
    custom_args = kwargs.pop("args", [])
    combined_args = list(set(default_args + custom_args))
    
    ignore_default_args = kwargs.pop(
        "ignore_default_args",
        [
            "--enable-automation",
            "--enable-blink-features=IdleDetection",
            "--disable-extensions",
            "--disable-component-update",
        ],
    )
    viewport = kwargs.pop("viewport", None)

    channel_override = kwargs.pop("channel", None)
    browser_launch_kwargs = get_browser_launch_kwargs(channel=channel_override)
    
    launch_args = {
        "user_data_dir": user_data_dir,
        "headless": headless,
        "args": combined_args,
        "ignore_default_args": ignore_default_args,
        "viewport": viewport,
        **browser_launch_kwargs,
        **kwargs
    }

    try:
        from core.auth_status import sync_profile_storage
        sync_profile_storage(user_data_dir)
    except Exception:
        pass

    try:
        return playwright_instance.chromium.launch_persistent_context(**launch_args)
    except Exception as e:
        import tempfile
        from core.auth_status import clone_profile_for_fallback
        temp_profile = tempfile.mkdtemp(prefix="playwright_scrape_")
        try:
            clone_profile_for_fallback(user_data_dir, temp_profile)
        except Exception:
            pass
        launch_args["user_data_dir"] = temp_profile
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
                    except Exception:
                        page.click('button[type="submit"]', timeout=3000)

                try:
                    page.wait_for_url(lambda url: "login" not in url and "checkpoint" not in url and "challenge" not in url, timeout=10000)
                except Exception:
                    pass
                page.wait_for_timeout(random.randint(3000, 5000))

                if "challenge" in page.url or "checkpoint" in page.url:
                    logging.warning("⚠️ LinkedIn is asking for a security check. Please run scripts/login.py manually.")
                    LOGIN_FAILED = True
                elif "login" in page.url or "authwall" in page.url:
                    logging.error("❌ Auto-login failed (possibly due to headless mode). Please run scripts/login.py manually.")
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
            from core.config import get_clean_browser_page
            self.page = get_clean_browser_page(self._context)
            Stealth().apply_stealth_sync(self.page)
            # Warm-up: confirm login state once for the whole session
            try:
                self.page.goto('https://www.linkedin.com/feed/', wait_until='commit', timeout=15000)
                auto_login_if_needed(self.page)
            except Exception as fe:
                logging.debug(f"Feed warm-up non-critical error: {fe}")
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
    
    // Find post container elements on LinkedIn content search results
    let posts = Array.from(document.querySelectorAll(
        'li.reusable-search__result-container, ' +
        'div.feed-shared-update-v2, ' +
        'div[data-urn*="activity"], ' +
        'div[data-id*="activity"], ' +
        'div.search-results-container .artdeco-card, ' +
        'div.search-entity'
    ));

    // Fallback: search for elements containing activity URNs or control menus
    if (posts.length === 0) {
        let menuBtns = document.querySelectorAll(
            'button[aria-label*="Control Menu"], button[aria-label*="control menu" i], ' +
            '.feed-shared-control-menu__trigger, .artdeco-dropdown__trigger'
        );
        posts = Array.from(menuBtns).map(btn =>
            btn.closest('li.reusable-search__result-container') ||
            btn.closest('.feed-shared-update-v2') ||
            btn.closest('.search-entity') ||
            btn.closest('li') ||
            btn.parentElement?.parentElement?.parentElement
        ).filter(Boolean);
    }
    
    posts = Array.from(new Set(posts));

    if (posts.length === 0) { return document.body.innerText; }

    for (let post of posts) {
        let postUrl = "";
        
        // 1. Direct anchor href search for activity/post URL
        for (let a of post.querySelectorAll('a')) {
            if (a.href) {
                if (a.href.includes('/feed/update/urn:li:') || a.href.includes('/posts/') || a.href.includes('-activity-')) {
                    postUrl = a.href.split('?')[0];
                    break;
                }
            }
        }
        
        // 2. data-urn or data-id attribute extraction
        if (!postUrl) {
            let dataUrn = post.getAttribute('data-urn') || post.getAttribute('data-id') || post.querySelector('[data-urn]')?.getAttribute('data-urn') || post.querySelector('[data-id]')?.getAttribute('data-id');
            if (dataUrn) {
                let match = dataUrn.match(/(?:activity|ugcPost|share)[:\-]?(\d{18,20})/);
                if (match) {
                    postUrl = "https://www.linkedin.com/feed/update/urn:li:activity:" + match[1];
                }
            }
        }
        
        // 3. outerHTML regex extraction for activity ID
        if (!postUrl) {
            let outerMatch = post.outerHTML.match(/(?:urn:li:)?(?:activity|ugcPost|share)[:\-]?(\d{18,20})/);
            if (outerMatch) {
                postUrl = "https://www.linkedin.com/feed/update/urn:li:activity:" + outerMatch[1];
            }
        }
        
        // 4. Fallback to post author profile/company URL
        if (!postUrl) {
            let authorLink = post.querySelector('a[href*="/in/"], a[href*="/company/"]');
            if (authorLink && authorLink.href) {
                postUrl = authorLink.href.split('?')[0];
            }
        }
        
        let text = post.innerText;
        if (text && text.trim().length > 20) {
            if (postUrl) {
                result += "Post URL: " + postUrl + "\n";
            }
            result += "Post Text:\n" + text + "\n\n---END OF POST---\n\n";
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


def scrape_linkedin_guest_api(term, location, results_wanted=15, hours_old=None, low_competition=None):
    """High-speed zero-browser LinkedIn scraper using the public Guest API."""
    import datetime
    jobs = []
    try:
        from curl_cffi import requests as c_requests
        from bs4 import BeautifulSoup
        encoded_term = urllib.parse.quote(term)
        encoded_loc = urllib.parse.quote(location)
        base_url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={encoded_term}&location={encoded_loc}&sortBy=DD"
        if low_competition is None:
            from core.scorer import load_latest_config
            cfg = load_latest_config()
            low_competition = bool(cfg.get("LOW_COMPETITION_FILTER", False))

        if low_competition:
            base_url += "&f_EA=true"

        if hours_old:
            if hours_old <= 24:
                base_url += "&f_TPR=r86400"
            elif hours_old <= 168:
                base_url += "&f_TPR=r604800"
            else:
                base_url += "&f_TPR=r2592000"

        seen_urls = set()
        page = 0
        max_pages = 5

        while len(jobs) < results_wanted and page < max_pages:
            start_offset = page * 25
            url = f"{base_url}&start={start_offset}"
            r = c_requests.get(url, impersonate="chrome120", timeout=8)
            if r.status_code != 200 or not r.text:
                break

            soup = BeautifulSoup(r.text, 'html.parser')
            cards = soup.find_all('li')
            if not cards:
                break

            valid_cards_in_page = 0
            for card in cards:
                if len(jobs) >= results_wanted:
                    break
                a_tag = card.find('a', class_='base-card__full-link')
                if not a_tag or not a_tag.get('href'):
                    continue
                valid_cards_in_page += 1
                clean_url = a_tag['href'].split('?')[0]
                if clean_url in seen_urls or is_job_seen(clean_url):
                    continue
                seen_urls.add(clean_url)

                t_elem = card.find('h3', class_='base-search-card__title')
                comp_elem = card.find('h4', class_='base-search-card__subtitle')
                loc_elem = card.find('span', class_='job-search-card__location')
                time_tag = card.find('time')

                title = t_elem.text.strip() if t_elem else "Unknown"
                company = comp_elem.text.strip() if comp_elem else "Unknown"
                loc_val = loc_elem.text.strip() if loc_elem else location

                job_date = datetime.date.today()
                if time_tag and time_tag.get('datetime'):
                    try:
                        job_date = datetime.datetime.strptime(time_tag['datetime'][:10], "%Y-%m-%d").date()
                    except Exception:
                        pass

                card_job_id = make_job_id(title, company, clean_url)
                if is_job_id_seen(card_job_id):
                    refresh_republished_job(card_job_id, job_url=clean_url, date_posted=job_date)
                    continue

                # Fast fetch full description via job detail endpoint
                description = ""
                apply_url = None
                is_ea = None
                num_applicants = None
                m_id = re.search(r'(\d{8,12})', clean_url)
                if m_id:
                    try:
                        detail_url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{m_id.group(1)}"
                        dr = c_requests.get(detail_url, impersonate="chrome120", timeout=5)
                        if dr.status_code == 200 and dr.text:
                            dsoup = BeautifulSoup(dr.text, 'html.parser')
                            dtext = dsoup.find('div', class_='show-more-less-html__markup')
                            if dtext:
                                from scrapers.common import html_to_text
                                description = html_to_text(str(dtext))

                            apply_a = dsoup.find("a", class_=lambda c: c and "apply" in c) or dsoup.find("a", href=lambda h: h and ("/safety/go/" in h or "externalApply" in h))
                            if apply_a and apply_a.get("href"):
                                raw_href = apply_a["href"]
                                apply_url = resolve_canonical_apply_url(raw_href)
                                is_ea = False
                            apply_btn_soup = dsoup.find("button", class_=lambda c: c and "apply" in c)
                            if apply_btn_soup:
                                btn_text = apply_btn_soup.get_text(separator=" ", strip=True).lower()
                                if "easy apply" in btn_text:
                                    is_ea = True

                            if not apply_url and not is_ea:
                                apply_url = extract_embedded_apply_url(
                                    html_content=dr.text if hasattr(dr, 'text') else "",
                                    text_content=description
                                )

                            app_el = dsoup.find(class_=lambda c: c and ('num-applicants' in c or 'applicant-count' in c))
                            if app_el:
                                num_applicants = extract_applicant_count(app_el.get_text())
                            if num_applicants is None:
                                num_applicants = extract_applicant_count(dr.text)
                    except Exception:
                        pass

                jobs.append({
                    'title': title,
                    'company': company,
                    'location': loc_val,
                    'job_url': clean_url,
                    'apply_url': apply_url,
                    'is_easy_apply': is_ea,
                    'description': description,
                    'site': 'linkedin',
                    'is_remote': 'remote' in str(loc_val).lower() or 'remote' in location.lower(),
                    'date_posted': job_date,
                    'job_type': 'Not specified',
                    'num_applicants': num_applicants
                })

            if valid_cards_in_page == 0:
                break
            page += 1

        if jobs:
            logging.info(f"⚡ LinkedIn Guest API extracted {len(jobs)} jobs in < 2s.")
            return pd.DataFrame(jobs)
    except Exception as e:
        logging.debug(f"LinkedIn guest API failed: {e}")

    return pd.DataFrame(jobs)


def _do_scrape_linkedin_jobs(page, term, location, results_wanted=5, hours_old=None, low_competition=None):
    """Job-scraping logic using an existing page object."""
    import datetime
    jobs = []

    encoded_term = urllib.parse.quote(term)
    encoded_loc = urllib.parse.quote(location)
    base_search_url = f"https://www.linkedin.com/jobs/search/?keywords={encoded_term}&location={encoded_loc}&sortBy=DD"
    if low_competition is None:
        from core.scorer import load_latest_config
        cfg = load_latest_config()
        low_competition = bool(cfg.get("LOW_COMPETITION_FILTER", False))

    if low_competition:
        base_search_url += "&f_EA=true"

    if hours_old:
        if hours_old <= 24:
            tpr_val = 86400
        elif hours_old <= 168:
            tpr_val = 604800
        else:
            tpr_val = 2592000
        base_search_url += f"&f_TPR=r{tpr_val}"

    logging.info(f"🔍 Searching LinkedIn Jobs (Playwright): {term} in {location}")
    try:
        collected_links = []
        seen_collected = set()
        page_idx = 0
        max_search_pages = 3

        while len(collected_links) < results_wanted and page_idx < max_search_pages:
            url = f"{base_search_url}&start={page_idx * 25}" if page_idx > 0 else base_search_url
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

            raw_links = page.evaluate(_JOB_LINK_EXTRACTOR_JS)
            if not raw_links:
                break

            for u in raw_links:
                if len(collected_links) >= results_wanted:
                    break
                if u not in seen_collected and not is_job_seen(u):
                    seen_collected.add(u)
                    collected_links.append(u)

            page_idx += 1

        links = collected_links[:results_wanted]

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
                    except Exception:
                        pass

                # Direct DOM extraction (sub-millisecond, zero LLM tokens)
                title = page.evaluate("() => document.querySelector('.jobs-unified-top-card__job-title, .top-card-layout__title, h1')?.innerText.trim() || ''")
                company = page.evaluate("() => document.querySelector('.jobs-unified-top-card__company-name, .topcard__org-name-link, .job-details-jobs-unified-top-card__company-name')?.innerText.trim() || ''")
                loc_val = page.evaluate("() => document.querySelector('.jobs-unified-top-card__bullet, .topcard__flavor--bullet, .job-details-jobs-unified-top-card__bullet')?.innerText.trim() || ''")
                desc_html = page.evaluate("() => document.querySelector('.jobs-description__content, .show-more-less-html__markup, #job-details')?.innerHTML || ''")
                from scrapers.common import html_to_text
                desc = html_to_text(desc_html) if desc_html else ""
                setup_val = page.evaluate("""() => {
                    const main = document.querySelector('main') || document.body;
                    const chips = Array.from(main.querySelectorAll('span, button, div, a, li')).filter(el => {
                        const txt = (el.innerText || '').trim();
                        return el.children.length === 0 && /^(?:Hybrid|Remote|On-site|Onsite|حضوري|هجين|عن بعد)$/i.test(txt);
                    });
                    for (const chip of chips) {
                        const t = chip.innerText.trim();
                        if (/hybrid|هجين/i.test(t)) return 'Hybrid';
                        if (/remote|عن بعد/i.test(t)) return 'Remote';
                        if (/on-?site|حضوري/i.test(t)) return 'On-site';
                    }
                    const topText = (main.innerText || '').slice(0, 1500);
                    const m = topText.match(/\\b(Hybrid|Remote|On-site|Onsite)\\b/i);
                    if (m) {
                        const val = m[1].toLowerCase();
                        if (val === 'hybrid') return 'Hybrid';
                        if (val === 'remote') return 'Remote';
                        if (val.includes('site')) return 'On-site';
                    }
                    return null;
                }""")

                if not title:
                    # Fallback to JSON-LD if available
                    page_html = page.evaluate("document.documentElement.innerHTML")
                    json_ld = extract_json_ld(page_html)
                    if json_ld:
                        title = json_ld.get('title', '')
                        company = json_ld.get('company', company)
                        loc_val = json_ld.get('location', loc_val)
                        json_ld_desc = json_ld.get('description', '')
                        desc = html_to_text(json_ld_desc) if json_ld_desc else desc

                apply_info = page.evaluate("""() => {
                    let applyHref = null;
                    let isEasy = null;
                    const applyAnchor = document.querySelector('a.jobs-apply-button, a[href*="/safety/go/"], a[aria-label*="Apply to"], a.apply-button');
                    if (applyAnchor && applyAnchor.href) {
                        applyHref = applyAnchor.href;
                        isEasy = false;
                    }
                    const applyBtn = document.querySelector('button.jobs-apply-button, button[class*="apply"]');
                    if (applyBtn) {
                        const text = (applyBtn.innerText || '').trim().toLowerCase();
                        const dataUrl = applyBtn.getAttribute('data-apply-url');
                        applyHref = applyHref || dataUrl;
                        isEasy = text.includes('easy apply');
                    }
                    return { applyHref, isEasy };
                }""")
                apply_url = None
                raw_href = (apply_info or {}).get("applyHref")
                if raw_href:
                    apply_url = resolve_canonical_apply_url(raw_href)
                is_ea = (apply_info or {}).get("isEasy")

                if not apply_url and not is_ea:
                    apply_url = extract_embedded_apply_url(html_content=desc_html, text_content=desc)

                applicant_text = page.evaluate("""() => {
                    const el = document.querySelector('.jobs-unified-top-card__applicant-count, .num-applicants__caption, .jobs-unified-top-card__bullet--applicant-count, .job-details-jobs-unified-top-card__bullet');
                    if (el && /applicant|متقدم/i.test(el.innerText)) return el.innerText.trim();
                    const bullets = Array.from(document.querySelectorAll('.jobs-unified-top-card__bullet, .job-details-jobs-unified-top-card__bullet, span.tvm__text, .topcard__flavor--bullet'));
                    for (const b of bullets) {
                        if (/applicant|متقدم/i.test(b.innerText)) return b.innerText.trim();
                    }
                    return '';
                }""")
                num_applicants = extract_applicant_count(applicant_text)

                if title and title not in ("Unknown", "Not specified"):
                    is_rem = (setup_val == 'Remote') or ('remote' in str(loc_val).lower() or 'remote' in location.lower())
                    jobs.append({
                        'title': title,
                        'company': company or 'Unknown',
                        'location': loc_val or location,
                        'job_url': job_url,
                        'apply_url': apply_url,
                        'is_easy_apply': is_ea,
                        'description': desc,
                        'site': 'linkedin',
                        'is_remote': is_rem,
                        'workplace_setup': setup_val or ('Remote' if is_rem else 'On-site'),
                        'date_posted': datetime.date.today(),
                        'job_type': 'Not specified',
                        'num_applicants': num_applicants
                    })

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


def scrape_linkedin_jobs_playwright(term, location, results_wanted=5, hours_old=None, page=None, low_competition=None):
    """Scrape LinkedIn Jobs.
    
    Tries the high-speed Guest API first (< 2s, zero browser overhead).
    Falls back to Playwright if needed.
    """
    guest_df = scrape_linkedin_guest_api(term, location, results_wanted, hours_old, low_competition=low_competition)
    if guest_df is not None and not guest_df.empty:
        return guest_df

    if page is not None:
        return _do_scrape_linkedin_jobs(page, term, location, results_wanted, hours_old, low_competition=low_competition)

    # Standalone fallback
    with sync_playwright() as p:
        context = launch_persistent_browser(p, user_data_dir=USER_DATA_DIR, headless=True)
        pg = context.pages[0] if context.pages else context.new_page()
        Stealth().apply_stealth_sync(pg)
        try:
            return _do_scrape_linkedin_jobs(pg, term, location, results_wanted, hours_old, low_competition=low_competition)
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

    from scrapers.common import filter_linkedin_social_noise
    feed_text = filter_linkedin_social_noise(feed_text)

    valid_jobs = []
    ai_data = extract_feed_posts_with_ai(feed_text[:15000])

    if ai_data and not ai_data.get("error"):
        for job in ai_data.get("jobs", []):
            if job.get("is_job"):
                p_desc = filter_linkedin_social_noise(job.get('description', ''))
                p_apply = extract_embedded_apply_url(text_content=p_desc)
                valid_jobs.append({
                    'title': job.get('title', 'Unknown'),
                    'company': job.get('company', 'Unknown'),
                    'location': job.get('location', loc),
                    'job_url': job.get('job_url') or f"https://www.linkedin.com/search/results/content/?keywords={keyword}",
                    'apply_url': p_apply or None,
                    'description': p_desc,
                    'is_remote': 'remote' in str(job.get('location', '')).lower(),
                    'date_posted': job.get('date_posted') or date.today(),
                    'job_type': job.get('job_type') or 'Not specified',
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
