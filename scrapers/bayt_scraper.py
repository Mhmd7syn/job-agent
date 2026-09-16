import os
import sys
import urllib.parse
import pandas as pd
import datetime
import logging
import re
from bs4 import BeautifulSoup

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.database import is_job_seen

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

def scrape_bayt(search_term, location, results_wanted=15, hours_old=None, driver=None):
    jobs = []
    query = search_term
    
    loc_path = "egypt" if "egypt" in location.lower() else "international"
    url = f"https://www.bayt.com/en/{loc_path}/jobs/?q={urllib.parse.quote(query)}&options[sort][]=d"
    if hours_old:
        days = hours_old / 24
        if days <= 1:
            interval = 3
        elif days <= 7:
            interval = 2
        else:
            interval = 1
        url += f"&filters[jb_last_modification_date_interval][]={interval}"
    
    html_content = None
    # 1. Try fast curl_cffi HTTP request first
    try:
        from curl_cffi import requests as c_requests
        resp = c_requests.get(url, impersonate="chrome120", timeout=8)
        if resp.status_code == 200 and len(resp.text) > 10000 and "has-pointer-d" in resp.text:
            html_content = resp.text
    except Exception as e:
        logging.debug(f"Bayt fast HTTP fetch failed: {e}")

    # 2. Fallback to driver if Cloudflare challenge is presented
    if not html_content and driver is not None:
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
            html_content = driver.get_page_source()
        except Exception as e:
            logging.error(f"⚠️ Bayt driver error: {e}")

    if not html_content:
        return pd.DataFrame()

    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        job_cards = soup.find_all('li', class_='has-pointer-d')
        cutoff = (datetime.datetime.now() - datetime.timedelta(hours=hours_old)).date() if hours_old else None

        for card in job_cards:
            if len(jobs) >= results_wanted:
                break
                
            title_elem = card.find('h2')
            if not title_elem or not title_elem.find('a'):
                continue
                
            a_tag = title_elem.find('a')
            href = a_tag.get('href', '')
            if href.startswith('/'):
                href = "https://www.bayt.com" + href
                
            if is_job_seen(href):
                continue
                
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

            # Non-blocking description fetch
            full_desc = fetch_bayt_full_description(href)
            final_desc = full_desc if full_desc and len(full_desc) > len(card_desc) else card_desc

            jobs.append({
                'title': title,
                'company': company,
                'location': loc_val,
                'job_url': href,
                'job_type': 'Not specified',
                'description': final_desc,
                'is_remote': 'remote' in search_term.lower() or 'remote' in str(loc_val).lower(),
                'site': 'bayt',
                'date_posted': job_date
            })
            
    except Exception as e:
        logging.error(f"⚠️ Bayt parsing error: {e}")
            
    return pd.DataFrame(jobs)

if __name__ == "__main__":
    if sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
    print("Testing Bayt Scraper...")
    df = scrape_bayt("data scientist", "egypt", 5)
    print(df.head())
