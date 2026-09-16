import os
import sys
import re
import json
import time
import logging
import datetime
import urllib.parse
from bs4 import BeautifulSoup

# Ensure project root is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from core.llm_parser import extract_json_ld, extract_job_page_with_ai, extract_feed_posts_with_ai
from core.scorer import calculate_score, load_latest_config

# Setup logger
logger = logging.getLogger("link_scraper")


def _normalize_url(url: str) -> str:
    """Cleans and ensures scheme on URL."""
    url = (url or "").strip()
    if not url:
        return ""
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    return url


def detect_scraper_type(url: str) -> str:
    """Infers the appropriate scraper type from a URL string."""
    url_lower = (url or "").lower()
    if "linkedin.com" in url_lower or "eg.linkedin.com" in url_lower:
        if any(p in url_lower for p in ["/posts/", "/feed/update/", "activity", "ugcpost", "share:"]):
            return "linkedin_post"
        return "linkedin_job"
    elif "wuzzuf.net" in url_lower:
        return "wuzzuf"
    elif "tanqeeb.com" in url_lower:
        return "tanqeeb"
    elif "bayt.com" in url_lower:
        return "bayt"
    elif "glassdoor.com" in url_lower:
        return "glassdoor"
    elif "indeed.com" in url_lower:
        return "indeed"
    else:
        return "generic"


def _make_job_id(title: str, company: str, job_url: str = "") -> str:
    """Generates a clean, deterministic unique ID for the job."""
    t = re.sub(r'[^\w\s]', ' ', str(title or '').lower()).strip()
    c = re.sub(r'[^\w\s]', ' ', str(company or '').lower()).strip()
    jid = f"{re.sub(r'\s+', ' ', t)}|{re.sub(r'\s+', ' ', c)}"
    if len(jid.replace('|', '').strip()) < 3:
        import hashlib
        h = hashlib.md5((job_url or f"{title}_{company}").encode('utf-8')).hexdigest()[:12]
        jid = f"job_{h}"
    return jid


def _fix_job_type(raw_type: str, title: str = "", desc: str = "", is_scholarship: bool = False) -> str:
    """Normalizes job type into standard labels."""
    if is_scholarship:
        return "Scholarship"
    combined = f"{raw_type} {title} {desc}".lower()
    if any(k in combined for k in ["scholarship", "fellowship", "منحة", "منح", "grant"]):
        return "Scholarship"
    if any(k in combined for k in ["intern", "internship", "trainee", "working student"]):
        return "Internship"
    if any(k in combined for k in ["part time", "part-time", "دوام جزئي"]):
        return "Part-time"
    if any(k in combined for k in ["contract", "freelance", "عقد", "حر"]):
        return "Contract"
    if any(k in combined for k in ["full time", "full-time", "دوام كامل", "permanent"]):
        return "Full-time"
    return (raw_type.strip().title() if raw_type and raw_type.lower() not in ["not specified", "unknown", "nan"] else "Not specified")



def _fix_is_remote(location: str, title: str = "", desc: str = "", raw_is_remote: bool = False) -> bool:
    """Determines whether the job is remote."""
    if raw_is_remote is True or str(raw_is_remote).lower() == "true":
        return True
    combined = f"{location} {title} {desc}".lower()
    return any(k in combined for k in ["remote", "work from home", "عن بعد", "العمل من المنزل", "telecommute", "wfh"])


def _extract_company_from_desc(desc: str) -> str:
    """Attempts regex extraction of real company names if marked Confidential/Unknown."""
    generic_names = {'nan', 'confidential', 'unknown', 'not specified', 'not mentioned', 'staffing and recruiting', 'client', 'our client', 'a leading client', 'our multinational client', 'the company'}
    match = re.search(r'\b([A-Z][A-Za-z0-9\.\-\s&]{1,30}?)\s+(?:is\s+)?(?:looking|seeking|hiring|searching|recruiting)\s+(?:for|to|a|an)\b', desc[:800])
    if match:
        extracted = match.group(1).strip()
        ignore_words = ['we', 'our', 'the', 'this', 'here', 'currently', 'an', 'a', 'our client', 'client', 'someone', 'who', 'they', 'he', 'she']
        if extracted.lower() not in ignore_words and not any(gw in extracted.lower() for gw in ['our client', 'leading client', 'multinational', 'reputable company']):
            return extracted
    match_about = re.search(r'(?:^|\n|\.\s+)\s*About\s+([A-Z][A-Za-z0-9\.\-\s&]{2,30}?)(?:\s*:|\s*\.|\s*\n|\s+is|\s+was|\s+-)', desc)
    if match_about:
        extracted = match_about.group(1).strip()
        if extracted.lower() not in ['this job', 'the role', 'us', 'our company', 'the company', 'the position', 'the team', 'the client'] and not any(gw in extracted.lower() for gw in ['our client', 'leading client']):
            return extracted
    return ""


def _parse_relative_date(date_str: str) -> str:
    """Parses relative time strings like '5 days ago', '1 week ago', 'أمس' into YYYY-MM-DD."""
    today = datetime.date.today()
    if not date_str:
        return today.isoformat()
    ds = date_str.lower().strip()
    try:
        # Match direct YYYY-MM-DD
        m_iso = re.search(r'(\d{4}-\d{2}-\d{2})', ds)
        if m_iso:
            return m_iso.group(1)
        # Months
        m_month = re.search(r'(\d+)\s*(?:month|months|شهر|أشهر)', ds)
        if m_month:
            return (today - datetime.timedelta(days=int(m_month.group(1)) * 30)).isoformat()
        # Weeks
        m_week = re.search(r'(\d+)\s*(?:w|week|weeks|أسبوع|أسابيع)', ds)
        if m_week:
            return (today - datetime.timedelta(days=int(m_week.group(1)) * 7)).isoformat()
        # Days
        m_day = re.search(r'(\d+)\s*(?:d|day|days|يوم|أيام)', ds)
        if m_day:
            return (today - datetime.timedelta(days=int(m_day.group(1)))).isoformat()
        # Hours / minutes / today / yesterday
        if any(w in ds for w in ['yesterday', 'أمس', 'امس']):
            return (today - datetime.timedelta(days=1)).isoformat()
        if any(w in ds for w in ['today', 'hour', 'ساعة', 'دقيقة', 'minute', 'just now']):
            return today.isoformat()
    except Exception:
        pass
    return today.isoformat()


# ---------------------------------------------------------------------------
# Individual Platform Scrapers
# ---------------------------------------------------------------------------

def _scrape_linkedin_job(url: str) -> dict:
    """Scrapes a LinkedIn job view link via public Guest API with DOM/JSON-LD parsing."""
    from curl_cffi import requests as c_requests
    
    clean_url = url.split("?")[0]
    m_id = re.search(r'(?:currentJobId=|/jobs/view/|/jobs/view/\D*?)(\d{8,12})', url)
    job_id_num = m_id.group(1) if m_id else None

    # 1. Try public guest API detail endpoint
    if job_id_num:
        detail_url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id_num}"
        try:
            r = c_requests.get(detail_url, impersonate="chrome120", timeout=10)
            if r.status_code == 200 and r.text:
                soup = BeautifulSoup(r.text, "html.parser")
                title_elem = soup.find("h2", class_=lambda c: c and "top-card-layout__title" in c) or soup.find("h1")
                comp_elem = soup.find("a", class_=lambda c: c and "topcard__org-name-link" in c) or soup.find("span", class_=lambda c: c and "topcard__flavor" in c)
                loc_elem = soup.find("span", class_=lambda c: c and "topcard__flavor--bullet" in c)
                desc_elem = soup.find("div", class_="show-more-less-html__markup") or soup.find("div", class_=lambda c: c and "description" in c)
                time_tag = soup.find("span", class_=lambda c: c and "posted-time-ago__text" in c) or soup.find("time")

                # Extract criteria (Seniority, Employment type, etc.)
                criteria_items = []
                for item in soup.find_all("li", class_=lambda c: c and "description__job-criteria-item" in c):
                    criteria_items.append(item.get_text(separator=": ", strip=True))
                criteria_text = "\n".join(criteria_items)

                title = title_elem.text.strip() if title_elem else ""
                company = comp_elem.text.strip() if comp_elem else "Unknown"
                loc_val = loc_elem.text.strip() if loc_elem else "Not specified"
                desc = desc_elem.get_text(separator="\n", strip=True) if desc_elem else ""
                date_str = time_tag.text.strip() if time_tag else ""

                if criteria_text and desc:
                    desc = f"{criteria_text}\n\n{desc}"

                emp_type = "Not specified"
                for crit in criteria_items:
                    if "employment type" in crit.lower():
                        emp_type = crit.split(":")[-1].strip()

                if title and len(title) > 2:
                    return {
                        "title": title,
                        "company": company,
                        "location": loc_val,
                        "job_type": _fix_job_type(emp_type, title, desc),
                        "description": desc,
                        "date_posted": _parse_relative_date(date_str),
                        "site": "linkedin",
                        "job_url": clean_url
                    }
        except Exception as e:
            logger.debug(f"LinkedIn guest API fetch failed: {e}")

    # 2. Fallback to Playwright persistent session
    try:
        from scrapers.playwright_scraper import LinkedInSession
        with LinkedInSession() as page:
            if page:
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(1000)
                # Click see more if present
                try:
                    see_more = page.query_selector('.show-more-less-html__button, button[aria-label*="more" i]')
                    if see_more:
                        see_more.click()
                except Exception:
                    pass

                title = page.evaluate("() => document.querySelector('.jobs-unified-top-card__job-title, .top-card-layout__title, h1')?.innerText.trim() || ''")
                company = page.evaluate("() => document.querySelector('.jobs-unified-top-card__company-name, .topcard__org-name-link, .job-details-jobs-unified-top-card__company-name')?.innerText.trim() || ''")
                loc_val = page.evaluate("() => document.querySelector('.jobs-unified-top-card__bullet, .topcard__flavor--bullet, .job-details-jobs-unified-top-card__bullet')?.innerText.trim() || ''")
                desc = page.evaluate("() => document.querySelector('.jobs-description__content, .show-more-less-html__markup, #job-details')?.innerText.trim() || ''")

                if title:
                    return {
                        "title": title,
                        "company": company or "Unknown",
                        "location": loc_val or "Not specified",
                        "job_type": _fix_job_type("", title, desc),
                        "description": desc,
                        "date_posted": datetime.date.today().isoformat(),
                        "site": "linkedin",
                        "job_url": clean_url
                    }
    except Exception as e:
        logger.warning(f"Playwright fallback for LinkedIn job failed: {e}")

    return {}


def _scrape_linkedin_post(url: str, raw_text: str = "") -> dict:
    """Scrapes a LinkedIn post or hiring feed update using Playwright and AI extraction."""
    post_text = (raw_text or "").strip()

    if not post_text:
        try:
            from scrapers.playwright_scraper import LinkedInSession
            with LinkedInSession() as page:
                if page:
                    page.goto(url, wait_until="domcontentloaded", timeout=18000)
                    page.wait_for_timeout(1500)
                    # Expand any "see more" buttons on the post
                    page.evaluate("""() => {
                        document.querySelectorAll('.feed-shared-inline-show-more-text__see-more-less-toggle, button.see-more, button[aria-label*="more" i]').forEach(b => b.click());
                    }""")
                    page.wait_for_timeout(500)

                    post_text = page.evaluate("""() => {
                        let article = document.querySelector('.feed-shared-update-v2, article, main');
                        return article ? article.innerText : document.body.innerText;
                    }""")
        except Exception as e:
            logger.warning(f"Playwright error loading LinkedIn post: {e}")

    if not post_text or len(post_text) < 30:
        # Try fast HTTP request with curl_cffi in case og:description is present
        try:
            from curl_cffi import requests as c_requests
            r = c_requests.get(url, impersonate="chrome120", timeout=8)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                meta = soup.find("meta", property="og:description") or soup.find("meta", attrs={"name": "description"})
                if meta and meta.get("content") and len(meta["content"]) > 40:
                    post_text = meta["content"]
        except Exception:
            pass

    if not post_text:
        raise ValueError("Could not extract post content from LinkedIn. Please ensure the link is accessible or paste the post text.")

    # Process post text with Gemini AI
    ai_data = extract_feed_posts_with_ai(f"Post URL: {url}\n\n{post_text[:12000]}")
    if ai_data and not ai_data.get("error"):
        jobs = ai_data.get("jobs", [])
        if jobs:
            j = jobs[0]
            title = j.get("title", "Unknown")
            company = j.get("company", "Unknown")
            loc_val = j.get("location", "Not specified")
            desc = j.get("description") or post_text
            job_type = j.get("job_type", "Not specified")
            date_posted = j.get("date_posted") or datetime.date.today().isoformat()

            return {
                "title": title,
                "company": company,
                "location": loc_val,
                "job_type": _fix_job_type(job_type, title, desc),
                "description": desc,
                "date_posted": _parse_relative_date(date_posted),
                "site": "linkedin_posts",
                "job_url": url
            }

    # Fallback to general job page AI extraction
    ai_page = extract_job_page_with_ai(post_text[:10000])
    if ai_page and not ai_page.get("error"):
        return {
            "title": ai_page.get("title", "Job Posting"),
            "company": ai_page.get("company", "Unknown"),
            "location": ai_page.get("location", "Not specified"),
            "job_type": _fix_job_type(ai_page.get("job_type", "Not specified")),
            "description": ai_page.get("description") or post_text,
            "date_posted": _parse_relative_date(ai_page.get("date_posted")),
            "site": "linkedin_posts",
            "job_url": url
        }

    return {
        "title": "LinkedIn Job Post",
        "company": "Unknown",
        "location": "Not specified",
        "job_type": "Not specified",
        "description": post_text[:2000],
        "date_posted": datetime.date.today().isoformat(),
        "site": "linkedin_posts",
        "job_url": url
    }


def _scrape_wuzzuf(url: str) -> dict:
    """Scrapes a Wuzzuf job posting page."""
    from curl_cffi import requests as c_requests
    
    r = c_requests.get(url, impersonate="chrome120", timeout=10)
    if r.status_code != 200:
        raise ValueError(f"Wuzzuf returned status code {r.status_code}")

    soup = BeautifulSoup(r.text, "html.parser")
    title_elem = soup.find("h1")
    title = title_elem.text.strip() if title_elem else ""

    # Company
    comp_elem = soup.find("a", href=lambda h: h and ("/jobs/careers/" in h or "/company/" in h)) or soup.find("a", class_=lambda c: c and "css-1557q9l" in c)
    company = comp_elem.text.strip() if comp_elem else ""

    # Location
    loc_elem = soup.find("span", class_=lambda c: c and "css-97682w" in c) or soup.find("strong", class_=lambda c: c and "location" in str(c).lower())
    loc_val = loc_elem.text.strip() if loc_elem else "Egypt"

    # Description and body text
    for s in soup(["script", "style", "nav", "header", "footer"]):
        s.decompose()
    clean_text = soup.get_text(separator="\n", strip=True)

    # If title or company missing, let AI extract from page
    if not title or not company:
        ai_res = extract_job_page_with_ai(clean_text[:8000])
        if ai_res and not ai_res.get("error"):
            title = title or ai_res.get("title", "Unknown")
            company = company or ai_res.get("company", "Unknown")
            loc_val = loc_val or ai_res.get("location", "Egypt")
            desc = ai_res.get("description", clean_text)
            return {
                "title": title,
                "company": company,
                "location": loc_val,
                "job_type": _fix_job_type(ai_res.get("job_type", "Full-time"), title, desc),
                "description": desc,
                "date_posted": _parse_relative_date(ai_res.get("date_posted")),
                "site": "wuzzuf",
                "job_url": url
            }

    return {
        "title": title,
        "company": company or "Unknown",
        "location": loc_val or "Egypt",
        "job_type": _fix_job_type("Full-time", title, clean_text),
        "description": clean_text[:4000],
        "date_posted": datetime.date.today().isoformat(),
        "site": "wuzzuf",
        "job_url": url
    }


def _scrape_tanqeeb(url: str) -> dict:
    """Scrapes a Tanqeeb job page."""
    from curl_cffi import requests as c_requests
    
    r = c_requests.get(url, impersonate="chrome120", timeout=10)
    if r.status_code != 200:
        raise ValueError(f"Tanqeeb returned status code {r.status_code}")

    soup = BeautifulSoup(r.text, "html.parser")
    json_ld = extract_json_ld(r.text)
    if json_ld and json_ld.get("title"):
        json_ld["site"] = "tanqeeb"
        json_ld["job_url"] = url
        return json_ld

    title_elem = soup.find("h1") or soup.find("h2")
    title = title_elem.text.strip() if title_elem else ""

    desc_div = soup.find("div", class_=lambda c: c and any(k in str(c) for k in ["vacancy-desc", "job-description", "card-body", "details-content"]))
    desc = desc_div.get_text(separator="\n", strip=True) if desc_div else ""

    for s in soup(["script", "style", "nav", "header", "footer"]):
        s.decompose()
    page_text = soup.get_text(separator="\n", strip=True)

    if not title or len(desc) < 40:
        ai_res = extract_job_page_with_ai(page_text[:8000])
        if ai_res and not ai_res.get("error"):
            return {
                "title": ai_res.get("title", title or "Unknown"),
                "company": ai_res.get("company", "Unknown"),
                "location": ai_res.get("location", "Egypt"),
                "job_type": _fix_job_type(ai_res.get("job_type", "Full-time")),
                "description": ai_res.get("description", desc or page_text),
                "date_posted": _parse_relative_date(ai_res.get("date_posted")),
                "site": "tanqeeb",
                "job_url": url
            }

    return {
        "title": title,
        "company": "Unknown",
        "location": "Egypt",
        "job_type": "Full-time",
        "description": desc or page_text[:4000],
        "date_posted": datetime.date.today().isoformat(),
        "site": "tanqeeb",
        "job_url": url
    }


def _scrape_bayt(url: str) -> dict:
    """Scrapes a Bayt job posting page."""
    from curl_cffi import requests as c_requests
    
    r = c_requests.get(url, impersonate="chrome120", timeout=10)
    if r.status_code != 200:
        raise ValueError(f"Bayt returned status code {r.status_code}")

    json_ld = extract_json_ld(r.text)
    if json_ld and json_ld.get("title"):
        json_ld["site"] = "bayt"
        json_ld["job_url"] = url
        return json_ld

    soup = BeautifulSoup(r.text, "html.parser")
    title_elem = soup.find("h1")
    title = title_elem.text.strip() if title_elem else ""

    for s in soup(["script", "style", "nav", "header", "footer"]):
        s.decompose()
    clean_text = soup.get_text(separator="\n", strip=True)

    ai_res = extract_job_page_with_ai(clean_text[:8000])
    if ai_res and not ai_res.get("error"):
        return {
            "title": ai_res.get("title", title or "Unknown"),
            "company": ai_res.get("company", "Unknown"),
            "location": ai_res.get("location", "Middle East"),
            "job_type": _fix_job_type(ai_res.get("job_type", "Full-time")),
            "description": ai_res.get("description", clean_text),
            "date_posted": _parse_relative_date(ai_res.get("date_posted")),
            "site": "bayt",
            "job_url": url
        }

    return {
        "title": title or "Bayt Job",
        "company": "Unknown",
        "location": "Middle East",
        "job_type": "Full-time",
        "description": clean_text[:4000],
        "date_posted": datetime.date.today().isoformat(),
        "site": "bayt",
        "job_url": url
    }


def _scrape_generic(url: str, raw_text: str = "") -> dict:
    """Universal scraper for any job board or ATS (Greenhouse, Lever, Workday, etc.)."""
    from curl_cffi import requests as c_requests
    
    # If user provided raw text directly
    if raw_text and len(raw_text.strip()) > 50:
        ai_data = extract_job_page_with_ai(raw_text[:12000])
        if ai_data and not ai_data.get("error"):
            return {
                "title": ai_data.get("title", "Unknown"),
                "company": ai_data.get("company", "Unknown"),
                "location": ai_data.get("location", "Not specified"),
                "job_type": _fix_job_type(ai_data.get("job_type", "Not specified")),
                "description": ai_data.get("description") or raw_text,
                "date_posted": _parse_relative_date(ai_data.get("date_posted")),
                "site": "web",
                "job_url": url
            }

    html_content = ""
    try:
        r = c_requests.get(url, impersonate="chrome120", timeout=12)
        if r.status_code == 200:
            html_content = r.text
    except Exception as e:
        logger.debug(f"curl_cffi fetch failed for {url}: {e}")

    # 1. Check Schema.org JSON-LD
    if html_content:
        json_ld = extract_json_ld(html_content)
        if json_ld and json_ld.get("title") and len(json_ld.get("description", "")) > 30:
            domain = urllib.parse.urlparse(url).netloc.replace("www.", "").split(".")[0]
            json_ld["site"] = domain or "web"
            json_ld["job_url"] = url
            return json_ld

    # 2. Extract HTML text content
    clean_text = ""
    if html_content:
        soup = BeautifulSoup(html_content, "html.parser")
        for s in soup(["script", "style", "svg", "nav", "footer", "noscript"]):
            s.decompose()
        clean_text = soup.get_text(separator=" \n ", strip=True)

    # 3. If HTML was empty or blocked, try browser fallback
    if not clean_text or len(clean_text) < 100:
        try:
            from scrapers.playwright_scraper import launch_persistent_browser, USER_DATA_DIR
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                context = launch_persistent_browser(p, user_data_dir=USER_DATA_DIR, headless=True)
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(1500)
                rendered_html = page.content()
                json_ld = extract_json_ld(rendered_html)
                if json_ld and json_ld.get("title"):
                    domain = urllib.parse.urlparse(url).netloc.replace("www.", "").split(".")[0]
                    json_ld["site"] = domain or "web"
                    json_ld["job_url"] = url
                    return json_ld
                clean_text = page.evaluate("() => document.body.innerText")
                context.close()
        except Exception as e:
            logger.warning(f"Browser fallback failed for {url}: {e}")

    if not clean_text or len(clean_text) < 40:
        raise ValueError(f"Could not load or extract text from {url}. Please verify the link or paste the text.")

    # 4. AI extraction via Gemini Flash Lite
    ai_data = extract_job_page_with_ai(clean_text[:12000])
    if ai_data and not ai_data.get("error"):
        domain = urllib.parse.urlparse(url).netloc.replace("www.", "").split(".")[0]
        return {
            "title": ai_data.get("title", "Unknown"),
            "company": ai_data.get("company", "Unknown"),
            "location": ai_data.get("location", "Not specified"),
            "job_type": _fix_job_type(ai_data.get("job_type", "Not specified")),
            "description": ai_data.get("description") or clean_text[:4000],
            "date_posted": _parse_relative_date(ai_data.get("date_posted")),
            "site": domain or "web",
            "job_url": url
        }

    raise ValueError("AI failed to extract structured job details from page content.")


# ---------------------------------------------------------------------------
# Main Public Interface
# ---------------------------------------------------------------------------

def scrape_job_from_url(url: str, scraper_type: str = "auto", raw_text: str = "", is_scholarship: bool = False) -> dict:
    """
    Main entry point to scrape, normalize, score, and prepare a job dictionary
    ready for database insertion.
    """
    url = _normalize_url(url)
    if not url and not raw_text:
        raise ValueError("Please provide a valid job URL or job post text.")

    has_scholarship_tag = is_scholarship or bool(re.search(r'(?:#scholarship|\bscholarships?\b|\bfellowships?\b|\bمنحة\b|\bمنح\b)', f"{url} {raw_text}", re.IGNORECASE))

    # Determine scraper type
    if not scraper_type or scraper_type == "auto":
        scraper_type = detect_scraper_type(url)

    logger.info(f"Scraping job using engine '{scraper_type}' from {url or 'raw text'}")

    raw_job = None
    if scraper_type == "linkedin_job":
        raw_job = _scrape_linkedin_job(url)
    elif scraper_type == "linkedin_post":
        raw_job = _scrape_linkedin_post(url, raw_text=raw_text)
    elif scraper_type == "wuzzuf":
        raw_job = _scrape_wuzzuf(url)
    elif scraper_type == "tanqeeb":
        raw_job = _scrape_tanqeeb(url)
    elif scraper_type == "bayt":
        raw_job = _scrape_bayt(url)
    else:
        # Generic, glassdoor, indeed, etc.
        raw_job = _scrape_generic(url, raw_text=raw_text)

    if not raw_job or not raw_job.get("title") or raw_job.get("title") in ["Unknown", "Not specified", ""]:
        # Try generic fallback if specific engine failed
        if scraper_type != "generic":
            logger.info("Specific scraper yielded empty result, trying universal generic scraper...")
            raw_job = _scrape_generic(url, raw_text=raw_text)

    if not raw_job or not raw_job.get("title"):
        raise ValueError("Could not extract job title and details from this link.")

    title = str(raw_job.get("title", "Unknown")).strip()
    company = str(raw_job.get("company", "Unknown")).strip()
    location = str(raw_job.get("location", "Not specified")).strip()
    description = str(raw_job.get("description", "")).strip()
    job_type = _fix_job_type(raw_job.get("job_type", "Not specified"), title, description, is_scholarship=has_scholarship_tag)
    site = raw_job.get("site") or detect_scraper_type(url)
    job_url = url or raw_job.get("job_url", "")

    # Clean company if generic
    if company.lower() in ["unknown", "confidential", "nan", ""]:
        extracted_comp = _extract_company_from_desc(description)
        if extracted_comp:
            company = extracted_comp

    is_remote = _fix_is_remote(location, title, description, raw_job.get("is_remote", False))
    date_posted = _parse_relative_date(str(raw_job.get("date_posted", "")))
    job_id = _make_job_id(title, company, job_url)

    job_dict = {
        "job_id": job_id,
        "title": title,
        "company": company,
        "location": location,
        "job_url": job_url,
        "job_type": job_type,
        "date_posted": date_posted,
        "site": site,
        "description": description,
        "is_remote": is_remote,
        "is_scholarship": has_scholarship_tag,
        "status": "pending",
        "is_applied": 0
    }

    # Calculate match score based on user's current configuration
    config = load_latest_config()
    score = calculate_score(job_dict, config=config)
    job_dict["relevance_score"] = float(score)

    return job_dict
