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

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.database import is_job_seen

_IMPERSONATE_PROFILES = ["chrome120", "chrome110", "chrome107", "edge99", "safari15_5"]

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
            logging.warning(f"    (Tanqeeb network issue. Retrying {attempt+1}/{retries}...)")
            time.sleep(1)
    return None

def fetch_tanqeeb_full_description(job_url):
    """Fetches the complete full job description and requirements from a Tanqeeb job page."""
    if not job_url or 'egypt.tanqeeb.com/jobs/search' in job_url:
        return ""
    try:
        response = fetch_with_retries(job_url, retries=2, timeout=6)
        if response and response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            desc_div = (
                soup.find('div', class_=lambda c: c and any(k in str(c) for k in ['vacancy-desc', 'job-description', 'card-body', 'details-content'])) or
                soup.find('section', class_=lambda c: c and 'description' in str(c))
            )
            if desc_div:
                text = desc_div.get_text(separator='\n', strip=True)
                if len(text) > 80:
                    return text
    except Exception as e:
        logging.debug(f"Tanqeeb full desc fetch error for {job_url}: {e}")
    return ""

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
    while len(jobs) < results_wanted and page <= 3:
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
                if len(jobs) >= results_wanted:
                    break

                href = a_tag['href']
                if href.startswith('/'):
                    href = "https://egypt.tanqeeb.com" + href
                elif not href.startswith('http'):
                    href = "https://egypt.tanqeeb.com/" + href

                if is_job_seen(href):
                    continue

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
                        card.find('span', class_='search-job-source') or
                        card.find('div', class_='search-job-top-tags') or
                        card.find('span', class_=lambda c: c and 'company' in str(c))
                    )
                    if comp_elem:
                        company = comp_elem.text.strip()

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

                full_desc = fetch_tanqeeb_full_description(href) if href != url else ""
                final_desc = full_desc if full_desc and len(full_desc) > len(card_desc) else card_desc

                jobs.append({
                    'title': title,
                    'company': company,
                    'location': loc_val,
                    'job_url': href,
                    'job_type': 'Not specified',
                    'description': final_desc,
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
        
    return pd.DataFrame(jobs)

if __name__ == "__main__":
    print("Testing Tanqeeb Scraper...")
    df = scrape_tanqeeb("data scientist", "egypt", 5)
    print(df.head())
