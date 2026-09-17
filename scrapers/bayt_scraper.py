import os
import sys
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

def fetch_bayt_full_description(job_url):
    """Fetches the complete full job description and requirements via lightweight HTTP."""
    if not job_url or 'bayt.com/en/' not in job_url:
        return ""
    try:
        from curl_cffi import requests as c_requests
        resp = c_requests.get(
            job_url,
            impersonate="chrome120",
            timeout=5
        )
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.content, 'html.parser')
            desc_div = soup.find('div', class_=lambda c: c and any(k in str(c) for k in ['card-content', 't-break', 'job-description', 'is-space-bottom-large']))
            if desc_div:
                text = desc_div.get_text(separator='\n', strip=True)
                if len(text) > 80:
                    return text
    except Exception as e:
        logging.debug(f"Bayt HTTP fetch failed for {job_url}: {e}")

    return ""

def _fetch_bayt_page(url, driver=None):
    """Fetches a Bayt page via fast HTTP first, with driver fallback for Cloudflare."""
    try:
        from curl_cffi import requests as c_requests
        resp = c_requests.get(url, impersonate="chrome120", timeout=8)
        if resp.status_code == 200 and len(resp.text) > 10000 and "has-pointer-d" in resp.text:
            return resp.text
    except Exception as e:
        logging.debug(f"Bayt fast HTTP fetch failed: {e}")

    if driver is not None:
        try:
            driver.uc_open_with_reconnect(url, 4)
            try:
                driver.uc_gui_click_captcha()
            except Exception:
                pass
            try:
                driver.wait_for_element('li.has-pointer-d', timeout=8)
            except Exception:
                pass
            return driver.get_page_source()
        except Exception as e:
            logging.error(f"⚠️ Bayt driver error: {e}")

    return None

def scrape_bayt(search_term, location, results_wanted=15, hours_old=None, driver=None):
    jobs = []
    query = search_term
    
    loc_path = "egypt" if "egypt" in location.lower() else "international"
    base_url = f"https://www.bayt.com/en/{loc_path}/jobs/?q={urllib.parse.quote(query)}&options[sort][]=d"
    if hours_old:
        days = hours_old / 24
        if days <= 1:
            interval = 3
        elif days <= 7:
            interval = 2
        else:
            interval = 1
        base_url += f"&filters[jb_last_modification_date_interval][]={interval}"
    
    cutoff = (datetime.datetime.now() - datetime.timedelta(hours=hours_old)).date() if hours_old else None
    candidates = []
    seen_urls = set()
    page = 1
    max_pages = 3

    try:
        while len(candidates) < results_wanted and page <= max_pages:
            url = f"{base_url}&page={page}"
            html_content = _fetch_bayt_page(url, driver=driver)
            if not html_content:
                break

            soup = BeautifulSoup(html_content, 'html.parser')
            job_cards = soup.find_all('li', class_='has-pointer-d')
            if not job_cards:
                break

            added_in_page = 0
            for card in job_cards:
                if len(candidates) >= results_wanted:
                    break
                    
                title_elem = card.find('h2')
                if not title_elem or not title_elem.find('a'):
                    continue
                    
                a_tag = title_elem.find('a')
                href = a_tag.get('href', '')
                if href.startswith('/'):
                    href = "https://www.bayt.com" + href
                    
                if href in seen_urls or is_job_seen(href):
                    continue
                seen_urls.add(href)
                    
                title = a_tag.text.strip()
                if not title:
                    continue

                company_elem = card.find('b', class_='p10r')
                company = company_elem.text.strip() if company_elem else "Unknown"

                loc_elem = card.find('span', class_='t-mute')
                loc_val = loc_elem.text.strip() if loc_elem else location

                desc_elem = card.find('div', class_='t-small')
                card_desc = desc_elem.text.strip() if desc_elem else ""

                # Parse date
                job_date = datetime.datetime.now().date()
                date_elem = card.find('div', class_='t-mute') or card.find('span', class_='t-mute')
                if date_elem:
                    raw_d = date_elem.text.lower()
                    m_days = re.search(r'(\d+)\s+day', raw_d)
                    if m_days:
                        job_date = (datetime.datetime.now() - datetime.timedelta(days=int(m_days.group(1)))).date()
                    elif 'yesterday' in raw_d or 'أمس' in raw_d:
                        job_date = (datetime.datetime.now() - datetime.timedelta(days=1)).date()

                if cutoff and job_date < cutoff:
                    continue

                candidates.append({
                    'title': title,
                    'company': company,
                    'location': loc_val,
                    'job_url': href,
                    'job_type': 'Not specified',
                    'description': card_desc,
                    'is_remote': 'remote' in search_term.lower() or 'remote' in str(loc_val).lower(),
                    'site': 'bayt',
                    'date_posted': job_date
                })
                added_in_page += 1

            if added_in_page == 0:
                break
            page += 1

        # Concurrent description fetching
        def _fetch_desc(job):
            try:
                full_desc = fetch_bayt_full_description(job['job_url'])
                if full_desc and len(full_desc) > len(job['description']):
                    job['description'] = full_desc
            except Exception as e:
                logging.debug(f"Bayt desc fetch failed for {job['job_url']}: {e}")
            return normalize_job_dict(job)

        if candidates:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(candidates), 5)) as executor:
                jobs = list(executor.map(_fetch_desc, candidates))
            
    except Exception as e:
        logging.error(f"⚠️ Bayt parsing error: {e}")
            
    return pd.DataFrame(jobs)

if __name__ == "__main__":
    if sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
    print("Testing Bayt Scraper...")
    df = scrape_bayt("data scientist", "egypt", 5)
    print(df.head())
