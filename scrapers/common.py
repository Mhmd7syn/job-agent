import json
import logging
import concurrent.futures
from typing import Dict, Any, Optional, List, Callable, Union
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


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
                clean_desc = BeautifulSoup(raw_desc, 'html.parser').get_text(separator='\n', strip=True)
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
