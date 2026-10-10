import os
import sys
import urllib.parse
from curl_cffi import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import random
import datetime
import logging
import re
import concurrent.futures

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.database import is_job_seen
from core.job_utils import normalize_job_dict, normalize_site, make_job_id

_IMPERSONATE_PROFILES = ["chrome120", "chrome110"]

SCRAPED_PLATFORMS = {
    'linkedin': ['linkedin.com', 'lnkd.in'],
    'wuzzuf': ['wuzzuf.net'],
    'bayt': ['bayt.com'],
    'glassdoor': ['glassdoor.com'],
    'indeed': ['indeed.com'],
}

def get_scraped_site_from_url(url: str):
    """Returns the scraped platform name if url belongs to one of our target platforms, else None."""
    if not url:
        return None
    url_lower = url.lower()
    for site, domains in SCRAPED_PLATFORMS.items():
        if any(d in url_lower for d in domains):
            return site
    return None

def fetch_with_retries(url, retries=3, timeout=15):
    for attempt in range(retries):
        try:
            response = requests.get(
                url,
                impersonate=random.choice(_IMPERSONATE_PROFILES),
                timeout=timeout
            )
            if response.status_code == 200:
                return response
            if response.status_code in (403, 429):
                logging.warning(f"    (Tanqeeb blocked ({response.status_code}). Retrying {attempt+1}/{retries}...)")
        except Exception as e:
            logging.warning(f"    (Tanqeeb network issue. Retrying {attempt+1}/{retries}...): {e}")
            time.sleep(1)
    return None

def _parse_tanqeeb_soup(soup):
    import json
    company = ""
    desc = ""
    apply_url = ""

    # 1. Schema.org JSON-LD
    for s in soup.find_all('script', type='application/ld+json'):
        try:
            d = json.loads(s.string or '{}')
            if d.get('@type') == 'JobPosting':
                if d.get('description'):
                    desc = BeautifulSoup(d['description'], 'html.parser').get_text(separator='\n', strip=True)
                if d.get('hiringOrganization', {}).get('name'):
                    company = d['hiringOrganization']['name'].strip()
                if d.get('url') and 'tanqeeb.com' not in d.get('url'):
                    apply_url = d['url'].strip()
        except Exception:
            pass

    if desc and len(desc) > 30:
        return {'description': desc, 'company': company, 'apply_url': apply_url, 'site_name': ''}

    # 2. Modern DOM
    desc_div = (
        soup.find('div', class_=lambda c: c and any(k in str(c) for k in ['vacancy-desc', 'job-description', 'card-body', 'details-content'])) or
        soup.find('section', class_=lambda c: c and 'description' in str(c))
    )
    if desc_div:
        text = desc_div.get_text(separator='\n', strip=True)
        if len(text) > 80:
            return {'description': text, 'company': company, 'apply_url': apply_url, 'site_name': ''}

    return {'description': desc, 'company': company, 'apply_url': apply_url, 'site_name': ''}

_TANQEEB_DETAILS_CACHE = {}

def fetch_tanqeeb_job_details(job_url):
    """Fetches the complete full job description, company, and apply URL from Tanqeeb v2 API or DOM."""
    if not job_url or 'egypt.tanqeeb.com/jobs/search' in job_url:
        return {'description': '', 'company': '', 'apply_url': '', 'site_name': ''}
    if job_url in _TANQEEB_DETAILS_CACHE:
        return _TANQEEB_DETAILS_CACHE[job_url]

    # 1. Fast path: Tanqeeb v2 API by extracting job ID
    m_id = re.search(r'(\d{6,10})', job_url)
    if m_id:
        job_id = m_id.group(1).lstrip('0')
        api_url = f"https://egypt.tanqeeb.com/v2/api/jobs/{job_id}"
        try:
            resp = fetch_with_retries(api_url, retries=2, timeout=8)
            if resp and resp.status_code == 200:
                data = resp.json().get('data', {})
                if data:
                    raw_desc = data.get('description') or ''
                    desc = BeautifulSoup(raw_desc, 'html.parser').get_text(separator='\n', strip=True) if raw_desc else ''
                    comp = data.get('company_name') or (data.get('company') or {}).get('name') or ''
                    apply_url = (data.get('apply_url') or '').strip()
                    site_name = (data.get('site_name') or '').strip()
                    res = {
                        'description': desc,
                        'company': comp,
                        'apply_url': apply_url,
                        'site_name': site_name
                    }
                    _TANQEEB_DETAILS_CACHE[job_url] = res
                    return res
        except Exception as e:
            logging.debug(f"Tanqeeb v2 API fetch error for {job_id}: {e}")

    # 2. Fallback: HTML scraping
    try:
        response = fetch_with_retries(job_url, retries=1, timeout=6)
        if response and response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            res = _parse_tanqeeb_soup(soup)
            _TANQEEB_DETAILS_CACHE[job_url] = res
            return res
    except Exception as e:
        logging.debug(f"Tanqeeb full desc fetch error for {job_url}: {e}")
    return {'description': '', 'company': '', 'apply_url': '', 'site_name': ''}

def fetch_tanqeeb_full_description(job_url):
    """Fetches the complete full job description and requirements from a Tanqeeb job page."""
    return fetch_tanqeeb_job_details(job_url).get('description', '')

def _parse_tanqeeb_date(date_str):
    if not date_str:
        return datetime.date.today()
    date_str_lower = date_str.lower().strip()
    try:
        # e.g. "10 July 2026"
        for fmt in ["%d %B %Y", "%d %b %Y", "%Y-%m-%d"]:
            try:
                return datetime.datetime.strptime(date_str_lower, fmt).date()
            except ValueError:
                pass
        # Relative dates: "X days ago" / "منذ X يوم"
        m_days = re.search(r'(\d+)\s*(?:day|days|يوم|أيام)', date_str_lower)
        if m_days:
            return datetime.date.today() - datetime.timedelta(days=int(m_days.group(1)))
        if any(w in date_str_lower for w in ['yesterday', 'أمس', 'امس']):
            return datetime.date.today() - datetime.timedelta(days=1)
        if any(w in date_str_lower for w in ['today', 'اليوم', 'hour', 'ساعة']):
            return datetime.date.today()
    except Exception:
        pass
    return datetime.date.today()

def scrape_tanqeeb(search_term, location, results_wanted=15, hours_old=None):
    jobs = []
    query = search_term
    if location.lower() == "worldwide" or location.lower() == "remote":
        query += " remote"
        
    base_url = f"https://egypt.tanqeeb.com/jobs/search?keywords={urllib.parse.quote(query)}"
    
    # Apply search period filter if hours_old is provided
    if hours_old:
        days_old = hours_old / 24
        if days_old <= 1:
            period = 1
        elif days_old <= 3:
            period = 3
        elif days_old <= 7:
            period = 7
        elif days_old <= 14:
            period = 14
        else:
            period = 30
        base_url += f"&refine[search_period]={period}"
    
    cutoff = (datetime.datetime.now() - datetime.timedelta(hours=hours_old)).date() if hours_old else None
    
    page = 1
    candidates = []
    seen_urls = set()
    while len(candidates) < results_wanted and page <= 3:
        url = f"{base_url}&page_no={page}"
        response = fetch_with_retries(url)
        if not response:
            break
            
        try:
            soup = BeautifulSoup(response.content, 'html.parser')
            # Extract job cards
            cards_found = []
            for h2 in soup.find_all(['h2', 'h3']):
                a = h2.find('a', href=True)
                if a and ('/jobs' in a['href'] or 'jobs-in-' in a['href'] or '/job/' in a['href']):
                    card = h2.find_parent('div', class_=lambda c: c and 'card' in c) or h2.find_parent('div')
                    cards_found.append((a, card))

            if not cards_found:
                # Fallback to direct anchor links
                for a in soup.find_all('a', class_=lambda c: c and 'title' in str(c), href=True):
                    if '/jobs' in a['href'] or 'jobs-in-' in a['href']:
                        card = a.find_parent('div', class_=lambda c: c and 'card' in c) or a.find_parent('div')
                        cards_found.append((a, card))

            if not cards_found:
                break

            added_in_page = 0
            for a_tag, card in cards_found:
                if len(candidates) >= results_wanted:
                    break

                href = a_tag['href']
                if href.startswith('/'):
                    href = "https://egypt.tanqeeb.com" + href
                elif not href.startswith('http'):
                    href = "https://egypt.tanqeeb.com/" + href

                if href in seen_urls or is_job_seen(href):
                    continue
                seen_urls.add(href)

                title = a_tag.text.strip()
                if not title:
                    continue

                company = "Unknown"
                loc_val = location
                date_posted = datetime.date.today()
                card_desc = ""

                if card:
                    card_desc = card.get_text(separator=' ', strip=True)
                    comp_elem = (
                        card.find('span', class_=lambda c: c and 'company' in str(c)) or
                        card.find('a', class_=lambda c: c and 'company' in str(c))
                    )
                    if comp_elem:
                        company = comp_elem.text.strip()
                    else:
                        src_elem = card.find('span', class_='search-job-source')
                        if src_elem:
                            s_txt = src_elem.text.strip()
                            if s_txt.lower() not in ['linkedin', 'naukri gulf', 'wuzzuf', 'bayt', 'forasna', 'tanqeeb']:
                                company = s_txt

                    loc_elem = (
                        card.find('span', class_='search-job-workplace-location') or
                        card.find('span', class_=lambda c: c and 'location' in str(c))
                    )
                    if loc_elem:
                        loc_val = loc_elem.text.strip()

                    date_elem = (
                        card.find('span', class_='search-job-date') or
                        card.find('span', class_=lambda c: c and 'date' in str(c))
                    )
                    if date_elem:
                        date_posted = _parse_tanqeeb_date(date_elem.text.strip())

                if cutoff and date_posted < cutoff:
                    continue

                candidates.append({
                    'title': title,
                    'company': company,
                    'location': loc_val,
                    'job_url': href,
                    'job_type': 'Not specified',
                    'description': card_desc,
                    'is_remote': 'remote' in search_term.lower() or 'remote' in str(loc_val).lower(),
                    'site': 'tanqeeb',
                    'date_posted': date_posted
                })
                added_in_page += 1

            if added_in_page == 0:
                break
                
        except Exception as e:
            logging.error(f"⚠️ Tanqeeb Scraper Error: {e}")
            break
            
        page += 1

    jobs = []
    def _fetch_desc(job):
        try:
            job_url = job.get('job_url', '')
            details = fetch_tanqeeb_job_details(job_url) if job_url and job_url != base_url else {}
            apply_url = (details.get('apply_url') or '').strip()

            if apply_url and get_scraped_site_from_url(apply_url):
                # If this apply_url has already been scraped or seen in DB, skip duplicate
                if is_job_seen(apply_url):
                    logging.debug(f"Skipping Tanqeeb job already seen via apply link: {apply_url}")
                    try:
                        from core.database import save_dropped_jobs
                        save_dropped_jobs([{'job_url': job_url, 'title': job.get('title', ''), 'company': job.get('company', ''), 'site': 'tanqeeb'}])
                    except Exception:
                        pass
                    return None
                try:
                    from scrapers.link_scraper import scrape_job_from_url
                    scraped_job = scrape_job_from_url(apply_url)
                    if scraped_job and scraped_job.get('title'):
                        scraped_job['apply_url'] = apply_url
                        try:
                            from core.database import save_dropped_jobs
                            save_dropped_jobs([{'job_url': job_url, 'title': job.get('title', ''), 'company': job.get('company', ''), 'site': 'tanqeeb'}])
                        except Exception:
                            pass
                        logging.info(f"    (Tanqeeb job '{job.get('title')}' scraped directly via {scraped_job.get('site')}: {apply_url})")
                        return scraped_job
                except Exception as e:
                    logging.debug(f"Direct link scrape failed for {apply_url}: {e}")

            # Standard Tanqeeb fallback
            full_desc = fetch_tanqeeb_full_description(job_url) if job_url != base_url else ""
            if full_desc and len(full_desc) > len(job.get('description', '')):
                job['description'] = full_desc
            if details.get('company') and (job.get('company') in ('Unknown', '', None) or job.get('company', '').lower() in ['linkedin', 'naukri gulf', 'wuzzuf', 'bayt', 'forasna', 'tanqeeb']):
                job['company'] = details['company']
            if apply_url:
                job['apply_url'] = apply_url

        except Exception as e:
            logging.debug(f"Tanqeeb desc/details fetch failed for {job.get('job_url')}: {e}")
        return normalize_job_dict(job)

    if candidates:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(candidates), 5)) as executor:
            raw_jobs = list(executor.map(_fetch_desc, candidates))
            jobs = [j for j in raw_jobs if j is not None]
        
    return pd.DataFrame(jobs)

if __name__ == "__main__":
    print("Testing Tanqeeb Scraper...")
    df = scrape_tanqeeb("data scientist", "egypt", 5)
    print(df.head())
