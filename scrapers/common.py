import json
import logging
import re
import urllib.parse
import concurrent.futures
from typing import Dict, Any, Optional, List, Callable, Union
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_BLOCK_TAGS = ['p', 'div', 'ul', 'ol', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']


def html_to_text(raw_html: str) -> str:
    """
    Converts an HTML fragment to plain text while keeping its layout:
    paragraphs and blocks are separated by blank lines, <br> starts a new
    line, and <li> items become '• ' bullets.
    """
    if not raw_html or not isinstance(raw_html, str):
        return ""

    soup = BeautifulSoup(raw_html, 'html.parser')
    for br in soup.find_all('br'):
        br.replace_with('\n')
    for block in soup.find_all(['p', 'div']):
        if block.find_parent('li'):
            if block.find_next_sibling(['p', 'div']):
                block.insert_after('\n')
            block.unwrap()
    for li in soup.find_all('li'):
        first_text = None
        for desc in li.descendants:
            if isinstance(desc, str) and desc.strip():
                first_text = desc
                break
        if first_text:
            cleaned = re.sub(r'^[•\-\*·–]\s*', '', str(first_text))
            first_text.replace_with(cleaned)
        li.insert_before('\n• ')
    for tag in soup.find_all(_BLOCK_TAGS):
        tag.insert_before('\n\n')
        tag.insert_after('\n\n')
    lines = [line.strip() for line in soup.get_text().split('\n')]
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(lines)).strip()


def fetch_page_content(
    url: str,
    driver=None,
    timeout: int = 8,
    min_length: int = 50,
    check_str: Optional[str] = None
) -> Optional[str]:
    """
    Fetches web page content using impersonated HTTP (curl_cffi) first,
    falling back to SeleniumBase driver if HTTP fails or gets blocked.
    """
    if not url:
        return None

    # 1. Fast HTTP fetch with Chrome TLS/JA3 impersonation
    try:
        from curl_cffi import requests as c_requests
        resp = c_requests.get(url, impersonate="chrome120", timeout=timeout)
        if getattr(resp, "status_code", None) == 200:
            text = ""
            if hasattr(resp, "text") and isinstance(resp.text, str):
                text = resp.text
            elif hasattr(resp, "content") and isinstance(resp.content, (bytes, bytearray)):
                text = resp.content.decode("utf-8", errors="ignore")
            elif hasattr(resp, "text"):
                text = str(resp.text)

            if len(text) >= min_length:
                if check_str is None or check_str in text:
                    return text
    except Exception as e:
        logger.debug(f"HTTP fetch failed for {url}: {e}")

    # 2. SeleniumBase live browser fallback
    if driver is not None:
        try:
            driver.uc_open_with_reconnect(url, 3)
            if "just a moment" in (getattr(driver, "title", "") or "").lower():
                try:
                    driver.uc_gui_click_captcha()
                except Exception:
                    pass
                if hasattr(driver, "sleep"):
                    driver.sleep(2)
            return driver.get_page_source()
        except Exception as e:
            logger.debug(f"Driver fetch failed for {url}: {e}")

    return None


def extract_json_ld_job(content: Union[BeautifulSoup, str]) -> Dict[str, Any]:
    """
    Unified Schema.org JSON-LD extractor for JobPosting objects.
    Parses title, company, description, location, apply URLs, and dates.
    """
    soup = content if isinstance(content, BeautifulSoup) else BeautifulSoup(content, 'html.parser')
    result: Dict[str, Any] = {
        'title': '',
        'company': '',
        'location': '',
        'description': '',
        'apply_url': '',
        'is_easy_apply': None,
        'date_posted': '',
        'job_type': 'Not specified'
    }

    scripts = soup.find_all('script', type='application/ld+json')
    for script in scripts:
        raw_text = script.string or script.get_text() or ''
        if not raw_text.strip():
            continue
        try:
            data = json.loads(raw_text)
        except (json.JSONDecodeError, Exception):
            continue

        candidates = []
        if isinstance(data, list):
            candidates = data
        elif isinstance(data, dict):
            if data.get('@type') == 'JobPosting':
                candidates = [data]
            elif '@graph' in data and isinstance(data['@graph'], list):
                candidates = data['@graph']

        for item in candidates:
            if not isinstance(item, dict) or item.get('@type') != 'JobPosting':
                continue

            # Title
            title = item.get('title') or item.get('name') or ''
            if title:
                result['title'] = str(title).strip()

            # Description (clean HTML tags)
            raw_desc = item.get('description', '')
            if raw_desc:
                clean_desc = html_to_text(raw_desc)
                if len(clean_desc) > len(result['description']):
                    result['description'] = clean_desc

            # Company
            org = item.get('hiringOrganization', {})
            if isinstance(org, dict):
                comp_name = org.get('name', '')
                if comp_name:
                    result['company'] = str(comp_name).strip()
            elif isinstance(org, str) and org.strip():
                result['company'] = org.strip()

            # Location
            loc_raw = item.get('jobLocation', {})
            if isinstance(loc_raw, list):
                loc_raw = loc_raw[0] if loc_raw else {}
            if isinstance(loc_raw, dict):
                addr = loc_raw.get('address', {})
                if isinstance(addr, dict):
                    loc_parts = [
                        addr.get('addressLocality', ''),
                        addr.get('addressRegion', ''),
                        addr.get('addressCountry', '')
                    ]
                    clean_loc = ', '.join(filter(None, loc_parts)).strip()
                    if clean_loc:
                        result['location'] = clean_loc
                elif isinstance(addr, str) and addr.strip():
                    result['location'] = addr.strip()
            elif isinstance(loc_raw, str) and loc_raw.strip():
                result['location'] = loc_raw.strip()

            # Direct Apply & Outbound Apply URL
            if 'directApply' in item:
                result['is_easy_apply'] = bool(item['directApply'])
            if item.get('url'):
                result['apply_url'] = str(item['url']).strip()

            # Date posted
            if item.get('datePosted'):
                result['date_posted'] = str(item['datePosted']).strip()

            # Employment Type
            emp_type = item.get('employmentType', '')
            if isinstance(emp_type, list):
                emp_type = emp_type[0] if emp_type else ''
            if emp_type:
                emp_map = {
                    'FULL_TIME': 'Full-time', 'PART_TIME': 'Part-time',
                    'CONTRACTOR': 'Contract', 'TEMPORARY': 'Temporary',
                    'INTERN': 'Internship', 'VOLUNTEER': 'Volunteer',
                }
                result['job_type'] = emp_map.get(str(emp_type).upper(), str(emp_type))

            # If we found at least description or company, return this match
            if result['description'] or result['company']:
                return result

    return result


def fetch_details_concurrently(
    items: List[Dict[str, Any]],
    fetch_fn: Callable[[Dict[str, Any]], Any],
    max_workers: int = 5
) -> List[Any]:
    """
    Executes detail fetching for a list of job items using a ThreadPoolExecutor.
    """
    if not items:
        return []
    workers = min(len(items), max_workers)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(fetch_fn, items))


SCRAPED_PLATFORMS = {
    'linkedin': ['linkedin.com', 'lnkd.in'],
    'wuzzuf': ['wuzzuf.net'],
    'bayt': ['bayt.com'],
    'glassdoor': ['glassdoor.com'],
    'indeed': ['indeed.com'],
}


def get_scraped_site_from_url(url: Optional[str]) -> Optional[str]:
    """Returns the scraped platform name if url belongs to one of our target platforms, else None."""
    if not url:
        return None
    url_lower = str(url).lower()
    for site, domains in SCRAPED_PLATFORMS.items():
        if any(d in url_lower for d in domains):
            return site
    return None


def reinject_scraped_job(
    job: Dict[str, Any],
    is_job_seen_fn: Optional[Callable[[str], bool]] = None
) -> Optional[Dict[str, Any]]:
    """
    Unified cross-platform apply link resolution.
    If job['apply_url'] points to one of our target platforms (and differs from the source site):
      1. If apply_url was already seen in the database, discards this job (returns None)
         and marks the referrer job_url in DB with score 0 to prevent re-querying.
      2. If not seen yet, directly scrapes the target job via scrape_job_from_url(apply_url),
         marks the referrer job_url in DB with score 0, and returns the newly scraped job.
      3. If direct scraping fails, falls back gracefully to the original job.
    If apply_url does not point to another scraped platform, returns job unchanged.
    """
    if not isinstance(job, dict):
        return job

    apply_url = str(job.get('apply_url') or '').strip()
    if not apply_url:
        return job

    target_site = get_scraped_site_from_url(apply_url)
    if not target_site:
        return job

    job_url = str(job.get('job_url') or '').strip()
    source_site = str(job.get('site') or '').strip().lower()

    # Do not re-scrape if apply_url is identical to job_url or stays within the same platform
    if apply_url == job_url or target_site == source_site:
        return job

    if is_job_seen_fn is None:
        from core.database import is_job_seen as is_job_seen_fn

    # 1. Deduplication check against SQLite database
    try:
        from core.database import save_job
        if is_job_seen_fn(apply_url):
            logger.info(f"Skipping {source_site or 'job'} '{job.get('title')}' - apply link already seen via {target_site}: {apply_url}")
            if job_url:
                try:
                    save_job({
                        'job_url': job_url,
                        'apply_url': apply_url,
                        'title': job.get('title', ''),
                        'company': job.get('company', ''),
                        'site': source_site or 'web',
                        'relevance_score': 0
                    })
                except Exception:
                    pass
            return None
    except Exception as e:
        logger.debug(f"is_job_seen check failed for {apply_url}: {e}")

    # 2. Re-inject and scrape directly from the target platform
    try:
        from scrapers.link_scraper import scrape_job_from_url
        scraped_job = scrape_job_from_url(apply_url)
        if scraped_job and scraped_job.get('title'):
            if not scraped_job.get('apply_url'):
                scraped_job['apply_url'] = apply_url
            if job_url:
                try:
                    from core.database import save_job
                    save_job({
                        'job_url': job_url,
                        'apply_url': apply_url,
                        'title': job.get('title', ''),
                        'company': job.get('company', ''),
                        'site': source_site or 'web',
                        'relevance_score': 0
                    })
                except Exception:
                    pass
            logger.info(f"    ({source_site or 'Job'} '{job.get('title')}' reinjected via direct {scraped_job.get('site')}: {apply_url})")
            return scraped_job
    except Exception as e:
        logger.debug(f"Direct link scrape failed for {apply_url}: {e}")

    return job


# ---------------------------------------------------------------------------
# Canonical Apply Link Resolution & Embedded ATS Extractor
# ---------------------------------------------------------------------------

SHORTLINK_DOMAINS = {
    "bit.ly", "tinyurl.com", "t.co", "lnkd.in", "goo.gl", "ow.ly",
    "buff.ly", "rebrand.ly", "cutt.ly", "is.gd", "v.gd"
}

ATS_DOMAINS = [
    "greenhouse.io", "boards.greenhouse.io", "job-boards.greenhouse.io",
    "lever.co", "jobs.lever.co",
    "ashbyhq.com", "jobs.ashbyhq.com",
    "myworkdayjobs.com", "workday.com",
    "smartrecruiters.com",
    "bamboohr.com",
    "taleo.net", "taleo.com",
    "workable.com", "apply.workable.com",
    "jobvite.com",
    "breezy.hr",
    "personio.com", "personio.de",
    "recruitee.com",
    "jazzhr.com",
    "rippling-ats.com", "rippling.com",
    "icims.com",
    "successfactors.com", "oraclecloud.com"
]

FORM_DOMAINS = [
    "forms.gle", "docs.google.com/forms", "forms.office.com", "forms.microsoft.com",
    "typeform.com", "airtable.com", "jotform.com", "tally.so"
]

_TRACKING_REDIRECT_PATTERNS = [
    r'/safety/go/',
    r'linkedin\.com/jobs/view/externalApply',
    r'tanqeeb\.com/jobs/redirect',
    r'tanqeeb\.com/apply',
    r'glassdoor\.com/partner/jobListing\.htm',
]

_EXCLUDED_DOMAINS = {
    "wuzzuf.net", "bayt.com", "tanqeeb.com", "glassdoor.com", "indeed.com",
    "facebook.com", "twitter.com", "x.com", "instagram.com", "youtube.com", "tiktok.com",
    "google.com", "play.google.com", "apple.com"
}

_CANONICAL_URL_CACHE: Dict[str, str] = {}


def resolve_canonical_apply_url(url: str, max_hops: int = 5, timeout: float = 4.0) -> str:
    """
    Resolves canonical destination apply URLs by unwrapping tracking redirects
    (/safety/go/?url=, /jobs/redirect?id=, etc.), following HTTP redirects
    for shortlink domains (lnkd.in, bit.ly, tinyurl), and following meta refresh tags.
    Safe against infinite loops, connection failures, and invalid schemes.
    """
    url = (url or "").strip()
    if not url or (not url.startswith("http://") and not url.startswith("https://")):
        return url or ""

    if url in _CANONICAL_URL_CACHE:
        return _CANONICAL_URL_CACHE[url]

    current = url
    visited = {current}

    for _ in range(max_hops):
        parsed = urllib.parse.urlparse(current)

        # 1. Query parameter redirect extraction (e.g. LinkedIn /safety/go/?url=, tracker?target=)
        qs = urllib.parse.parse_qs(parsed.query)
        extracted_target = None
        for param in ("url", "target", "dest", "destination", "redirect", "u", "link", "to"):
            if param in qs and qs[param]:
                val = qs[param][0].strip()
                if val.startswith("http://") or val.startswith("https://"):
                    extracted_target = val
                    break

        if extracted_target:
            if extracted_target not in visited:
                visited.add(extracted_target)
                current = extracted_target
                continue
            else:
                break

        # 2. Check if HTTP traversal is needed (shortlinks, aggregator trackers, or explicit redirect endpoints)
        domain = parsed.netloc.lower().replace("www.", "")
        is_shortlink = any(d in domain for d in SHORTLINK_DOMAINS)
        is_tracker = any(re.search(p, current, re.IGNORECASE) for p in _TRACKING_REDIRECT_PATTERNS)

        if not is_shortlink and not is_tracker:
            break

        # 3. Follow HTTP redirects safely
        try:
            from curl_cffi import requests as c_requests
            resp = c_requests.get(
                current,
                impersonate="chrome120",
                timeout=timeout,
                allow_redirects=False,
                stream=True
            )
            if resp.status_code in (301, 302, 303, 307, 308):
                loc = resp.headers.get("Location") or resp.headers.get("location")
                if loc:
                    next_url = urllib.parse.urljoin(current, loc.strip())
                    if next_url not in visited:
                        visited.add(next_url)
                        current = next_url
                        continue
                    else:
                        break

            if resp.status_code == 200:
                text_snippet = getattr(resp, "text", "")[:3000]
                meta_m = re.search(
                    r'<meta[^>]*?http-equiv=["\']?refresh["\']?[^>]*?content=["\']?\d+;\s*url=([^"\'>\s]+)',
                    text_snippet,
                    re.IGNORECASE
                )
                if meta_m:
                    next_url = urllib.parse.urljoin(current, meta_m.group(1).strip().strip('"\''))
                    if next_url not in visited:
                        visited.add(next_url)
                        current = next_url
                        continue
            break
        except Exception as e:
            logger.debug(f"HTTP redirect resolution failed for {current}: {e}")
            break

    if len(_CANONICAL_URL_CACHE) < 2000:
        _CANONICAL_URL_CACHE[url] = current
    return current


def extract_embedded_apply_url(
    html_content: str = "",
    text_content: str = "",
    base_url: str = ""
) -> Optional[str]:
    """
    Parses HTML DOM elements and job description plain text to identify embedded
    ATS portals (Greenhouse, Lever, Workday, Taleo, Ashby, SmartRecruiters, etc.),
    application forms (Google Forms, MS Forms, Typeform, etc.), and career links.
    Filters out aggregator links and social media trackers.
    """
    candidates: List[tuple[int, str]] = []  # (priority_score, url)

    # 1. Parse HTML DOM if provided
    if html_content and isinstance(html_content, str):
        try:
            soup = BeautifulSoup(html_content, "html.parser")

            # Check buttons / inputs with explicit data apply attributes
            for btn in soup.find_all(["button", "input", "div", "a"]):
                for attr in ("data-apply-url", "data-url", "data-job-url", "data-href"):
                    val = (btn.get(attr) or "").strip()
                    if val.startswith("http://") or val.startswith("https://"):
                        candidates.append((90, val))

            # Check <a> links
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"].strip()
                if not href.startswith("http://") and not href.startswith("https://"):
                    continue
                h_lower = href.lower()
                text_lower = a_tag.get_text(separator=" ", strip=True).lower()
                rel_attrs = " ".join(a_tag.get("class", [])).lower()

                # Score candidate link
                if any(ats in h_lower for ats in ATS_DOMAINS) or any(f in h_lower for f in FORM_DOMAINS):
                    candidates.append((100, href))
                elif any(sl in h_lower for sl in SHORTLINK_DOMAINS):
                    candidates.append((70, href))
                elif any(kw in text_lower or kw in rel_attrs for kw in ("apply", "submit", "career", "portal")):
                    candidates.append((60, href))
                elif any(kw in h_lower for kw in ("/careers", "/jobs", "/apply", "jobdetail", "req=")):
                    candidates.append((50, href))

            if not text_content:
                text_content = soup.get_text(separator=" \n ", strip=True)
        except Exception as e:
            logger.debug(f"DOM apply URL extraction error: {e}")

    # 2. Parse text content via regex
    if text_content and isinstance(text_content, str):
        # Extract all URLs
        urls = re.findall(r'https?://[^\s<>"\',;]+[^\s<>"\',;.!?)]', text_content)
        for u in urls:
            u_lower = u.lower()

            # Ignore aggregators, social platforms, and non-application LinkedIn URLs
            if any(ign in u_lower for ign in _EXCLUDED_DOMAINS):
                continue
            if "linkedin.com" in u_lower and not any(k in u_lower for k in ("/jobs/view", "/safety/go/")):
                continue

            if any(ats in u_lower for ats in ATS_DOMAINS) or any(f in u_lower for f in FORM_DOMAINS):
                candidates.append((100, u))
            elif any(sl in u_lower for sl in SHORTLINK_DOMAINS):
                candidates.append((65, u))
            elif any(kw in u_lower for kw in ("/careers", "/jobs/", "/apply", "jobdetail", "search-jobs", "req")):
                candidates.append((45, u))

    if not candidates:
        return None

    # Filter out excluded domains from candidates
    valid_candidates = []
    for score, cand_url in candidates:
        c_lower = cand_url.lower()
        if any(ign in c_lower for ign in _EXCLUDED_DOMAINS):
            continue
        if "linkedin.com" in c_lower and not any(k in c_lower for k in ("/jobs/view", "/safety/go/")):
            continue
        valid_candidates.append((score, cand_url))

    if not valid_candidates:
        return None

    # Sort candidates by priority score descending
    valid_candidates.sort(key=lambda x: x[0], reverse=True)
    best_url = valid_candidates[0][1]

    # Resolve any shortlink or query redirect on the selected candidate
    resolved = resolve_canonical_apply_url(best_url)
    return resolved or best_url


def is_valid_specific_apply_url(url: Optional[str], job_url: Optional[str] = None) -> bool:
    """
    Checks if a URL is a valid, specific job application destination suitable
    for cross-site deduplication (as opposed to generic domain roots, aggregator
    homepages, or self-referential job_urls).
    """
    if not url or not isinstance(url, str):
        return False

    url = url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        return False

    if job_url and url.rstrip("/") == job_url.strip().rstrip("/"):
        return False

    try:
        parsed = urllib.parse.urlparse(url)
        domain = parsed.netloc.lower().replace("www.", "")
        if any(agg in domain for agg in ("linkedin.com", "wuzzuf.net", "bayt.com", "tanqeeb.com", "glassdoor.com", "indeed.com")):
            return False

        path = parsed.path.strip("/")
        if not path or len(path) <= 1:
            return False

        if path.lower() in ("jobs", "careers", "en", "ar", "home", "search", "about", "index.html"):
            return False

        return True
    except Exception:
        return False

