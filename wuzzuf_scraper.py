import requests
import urllib.parse
from bs4 import BeautifulSoup
import pandas as pd

def scrape_wuzzuf(search_term, location, results_wanted=15):
    jobs = []
    query = search_term
    if location.lower() == "worldwide" or location.lower() == "remote":
        query += " remote"
        
    url = f"https://wuzzuf.net/search/jobs/?q={urllib.parse.quote(query)}"
    
    try:
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            return pd.DataFrame()
            
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
            
            jobs.append({
                'title': title,
                'company': company,
                'location': loc,
                'job_url': job_url,
                'job_type': job_type,
                'description': '',
                'is_remote': 'remote' in query.lower(),
                'site': 'wuzzuf'
            })
    except Exception as e:
        print(f"⚠️ Wuzzuf Scraper Error: {e}")
        
    return pd.DataFrame(jobs)
