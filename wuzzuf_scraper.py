import requests
import urllib.parse
from bs4 import BeautifulSoup
import pandas as pd
import time

def fetch_with_retries(url, retries=3, timeout=10):
    for attempt in range(retries):
        try:
            response = requests.get(url, timeout=timeout)
            if response.status_code == 200:
                return response
        except Exception as e:
            if attempt == retries - 1:
                print(f"⚠️ Network error on {url}: {e}")
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
        print(f"⚠️ Error parsing description for {url}: {e}")
        return ""

def scrape_wuzzuf(search_term, location, results_wanted=15):
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
        
        for card in job_cards[:results_wanted]:
            title_tag = card.find('h2', class_='css-193uk2c')
            if not title_tag or not title_tag.a: continue
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
                'site': 'wuzzuf'
            })
            
            # Small delay to respect rate limits
            time.sleep(1.5)
            
    except Exception as e:
        print(f"⚠️ Wuzzuf Scraper Error: {e}")
        
    return pd.DataFrame(jobs)
