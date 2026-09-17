import os
import sys
import json
import urllib.parse
import pandas as pd
import datetime
import logging
import re
import concurrent.futures
from bs4 import BeautifulSoup

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.database import is_job_seen
from core.job_utils import normalize_job_dict


def fetch_glassdoor_full_description(job_url: str, driver=None) -> str:
    """Fetches the complete full job description and requirements from a Glassdoor job page."""
    if not job_url or 'glassdoor.com/Job/jobs.htm' in job_url:
        return ""
    try:
        from curl_cffi import requests as c_requests
        resp = c_requests.get(job_url, impersonate="chrome120", timeout=5)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.content, 'html.parser')
            # 1. Look for description container
            desc_div = soup.find('div', class_=lambda c: c and any(k in str(c) for k in [
                'jobDescriptionContent', 'JobDetails_jobDescription', 'desc', 'JobDetails_jobDetailsContainer'
            ])) or soup.find('div', id='JobDescriptionContainer') or soup.find('section', class_=lambda c: c and 'job-description' in str(c))
            if desc_div:
                text = desc_div.get_text(separator='\n', strip=True)
                if len(text) > 80:
                    return text

            # 2. Check JSON-LD fallback
            for s in soup.find_all('script', type='application/ld+json'):
                try:
                    data = json.loads(s.string or "")
                    if isinstance(data, dict) and data.get('@type') == 'JobPosting' and data.get('description'):
                        clean_desc = BeautifulSoup(data['description'], 'html.parser').get_text(separator='\n', strip=True)
                        if len(clean_desc) > 80:
                            return clean_desc
                except Exception:
                    pass
    except Exception as e:
        logging.debug(f"Glassdoor full description fetch failed for {job_url}: {e}")
    return ""


def build_glassdoor_url(search_term: str, location: str, hours_old: int = None, page: int = 1) -> str:
    """
    Builds a clean Glassdoor search URL using locKeyword without hardcoded locId.
    Dynamically applies remote filters for remote searches and supports pagination via &p=page.
    """
    loc_str = (location or "").strip()
    is_remote = loc_str.lower() in ("remote", "worldwide", "anywhere") or "remote" in search_term.lower()

    params = [
        ("sc.keyword", search_term),
        ("sortBy", "date_desc"),
    ]

    if is_remote:
        params.append(("locKeyword", "Remote"))
        params.append(("remoteWorkType", "1"))
    elif loc_str:
        params.append(("locKeyword", loc_str))

    if hours_old:
        days = int(hours_old / 24)
        if days > 0:
            params.append(("fromAge", str(days)))

    if page > 1:
        params.append(("p", str(page)))

    query_str = urllib.parse.urlencode(params)
    return f"https://www.glassdoor.com/Job/jobs.htm?{query_str}"


def scrape_glassdoor(search_term, location, results_wanted=15, hours_old=None, driver=None):
    jobs = []

    if driver is None:
        return pd.DataFrame()

    try:
        candidates = []
        seen_urls = set()
        page = 1
        max_pages = 3

        while len(candidates) < results_wanted and page <= max_pages:
            url = build_glassdoor_url(search_term, location, hours_old, page=page)
            driver.uc_open_with_reconnect(url, 4)
            try:
                driver.uc_gui_click_captcha()
            except Exception:
                pass

            try:
                driver.wait_for_element('li', timeout=8)
            except Exception:
                pass

            html_content = driver.get_page_source()
            soup = BeautifulSoup(html_content, 'html.parser')
            job_cards = soup.find_all('li')
            if not job_cards:
                break

            added_in_page = 0
            for card in job_cards:
                if len(candidates) >= results_wanted:
                    break

                a_tag = card.find('a', href=True)
                if not a_tag:
                    continue

                href = a_tag['href']
                if not ('job-listing' in href or '/partner/' in href):
                    continue

                if href.startswith('/'):
                    href = "https://www.glassdoor.com" + href

                if href in seen_urls or is_job_seen(href):
                    continue
                seen_urls.add(href)

                title_elem = card.find(['a', 'span'], class_=lambda c: c and any(k in str(c) for k in ['JobTitle', 'job-title', 'jobTitle'])) or a_tag
                title = title_elem.text.strip() if title_elem else ""
                if not title or len(title) < 2:
                    continue

                comp_elem = card.find(['span', 'div', 'p'], class_=lambda c: c and any(k in str(c) for k in ['EmployerName', 'employer', 'company']))
                company = comp_elem.text.strip() if comp_elem else "Unknown"

                loc_elem = card.find(['div', 'span'], class_=lambda c: c and any(k in str(c) for k in ['location', 'Location', 'loc']))
                loc_val = loc_elem.text.strip() if loc_elem else location

                card_desc = card.get_text(separator=' ', strip=True)

                candidates.append({
                    'title': title,
                    'company': company,
                    'location': loc_val,
                    'job_url': href,
                    'job_type': 'Not specified',
                    'description': card_desc,
                    'is_remote': 'remote' in search_term.lower() or 'remote' in str(loc_val).lower(),
                    'site': 'glassdoor',
                    'date_posted': datetime.datetime.now().date()
                })
                added_in_page += 1

            if added_in_page == 0:
                break
            page += 1

        # Concurrent description fetching
        def _fetch_desc(job):
            try:
                full_desc = fetch_glassdoor_full_description(job['job_url'], driver=driver)
                if full_desc and len(full_desc) > len(job['description']):
                    job['description'] = full_desc
            except Exception as e:
                logging.debug(f"Glassdoor desc fetch failed for {job['job_url']}: {e}")
            return normalize_job_dict(job)

        if candidates:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(candidates), 5)) as executor:
                jobs = list(executor.map(_fetch_desc, candidates))

    except Exception as e:
        logging.error(f"⚠️ Glassdoor Scraper Error: {e}")

    return pd.DataFrame(jobs)


if __name__ == "__main__":
    if sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
    print("Testing Glassdoor Scraper...")
    df = scrape_glassdoor("data scientist", "egypt", 5)
    print(df.head())
