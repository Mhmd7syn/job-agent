import requests
import urllib.parse
from bs4 import BeautifulSoup
import pandas as pd
import time
import re
import datetime
import logging

def fetch_with_retries(url, retries=5, timeout=10):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    for attempt in range(retries):
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            if response.status_code == 200:
                return response
        except Exception as e:
            if attempt < retries - 1:
                logging.warning(f"    (Wuzzuf network issue. Retrying {attempt+1}/{retries}...)")
            else:
                logging.error(f"⚠️ Network error on {url} after {retries} attempts: {e}")
            time.sleep(2)
    return None

def get_wuzzuf_description(url):
    response = fetch_with_retries(url)
    if not response:
        return ""
    
    try:
        soup = BeautifulSoup(response.content, 'html.parser')
        desc_text = []
        # Look for typical description and requirements sections
        sections = soup.find_all('section')
        for sec in sections:
            title = sec.find('h2')
            if title and ('description' in title.text.lower() or 'requirement' in title.text.lower()):
                desc_text.append(sec.get_text(separator='\n', strip=True))
        
        if desc_text:
            return "\n".join(desc_text)
            
        # Fallback if specific sections not found
        return soup.get_text(separator=' ', strip=True)[:4000] 
    except Exception as e:
        logging.error(f"⚠️ Error parsing description for {url}: {e}")
        return ""

def parse_wuzzuf_date_to_hours(date_str):
    date_str = date_str.lower()
    hours = 0
    months = re.search(r'(\d+)\s*month', date_str)
    if months: hours += int(months.group(1)) * 30 * 24
    days = re.search(r'(\d+)\s*day', date_str)
    if days: hours += int(days.group(1)) * 24
    hr = re.search(r'(\d+)\s*hour', date_str)
    if hr: hours += int(hr.group(1))
    return hours

def scrape_wuzzuf(search_term, location, results_wanted=15, hours_old=None):
    jobs = []
    query = search_term
    if location.lower() == "worldwide" or location.lower() == "remote":
        query += " remote"
        
    url = f"https://wuzzuf.net/search/jobs/?q={urllib.parse.quote(query)}"
    
    response = fetch_with_retries(url)
    if not response:
        return pd.DataFrame()
        
    try:
        soup = BeautifulSoup(response.content, 'html.parser')
        job_cards = soup.find_all('div', class_=lambda c: c and 'css-pkv5jc' in c)
        
        for card in job_cards:
            if len(jobs) >= results_wanted:
                break
                
            title_tag = card.find('h2', class_='css-193uk2c')
            if not title_tag or not title_tag.a: continue
            
            # Extract date to filter old posts
            date_str = ""
            company_loc_div = card.find('div', class_='css-1k5ee52')
            if company_loc_div:
                date_tag = company_loc_div.find('div')
                if date_tag:
                    date_str = date_tag.text.strip()
            
            job_hours = parse_wuzzuf_date_to_hours(date_str) if date_str else 0
            if hours_old is not None and job_hours > hours_old:
                continue
                
            date_posted = datetime.datetime.now() - datetime.timedelta(hours=job_hours)
            
            title = title_tag.a.text.strip()
            job_url = "https://wuzzuf.net" + title_tag.a['href']
            
            company_tag = card.find('a', class_='css-ipsyv7')
            company = company_tag.text.replace('-', '').strip() if company_tag else "Unknown"
            
            loc_tag = card.find('span', class_='css-16x61xq')
            loc = loc_tag.text.strip() if loc_tag else location
            
            job_type_tags = card.find_all('span', class_=lambda c: c and 'eoyjyou0' in c)
            job_type = ", ".join([t.text.strip() for t in job_type_tags]) if job_type_tags else "Full Time"
            
            # Fetch the actual description
            description = get_wuzzuf_description(job_url)
            
            jobs.append({
                'title': title,
                'company': company,
                'location': loc,
                'job_url': job_url,
                'job_type': job_type,
                'description': description,
                'is_remote': 'remote' in query.lower(),
                'site': 'wuzzuf',
                'date_posted': date_posted.date()
            })
            
            # Small delay to respect rate limits
            time.sleep(1.5)
            
    except Exception as e:
        logging.error(f"⚠️ Wuzzuf Scraper Error: {e}")
        
    return pd.DataFrame(jobs)
