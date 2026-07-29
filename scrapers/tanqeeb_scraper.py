import urllib.parse
from curl_cffi import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import random
import datetime
import logging

from core.llm_parser import extract_feed_posts_with_ai
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
            time.sleep(2)
    return None

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
    
    page = 1
    while len(jobs) < results_wanted and page <= 5:
        url = f"{base_url}&page_no={page}"
        logging.info(f"    (Scraping Tanqeeb page {page}...)")
        response = fetch_with_retries(url)
        if not response:
            break
            
        try:
            soup = BeautifulSoup(response.content, 'html.parser')
            job_cards = soup.find_all('div', class_=lambda c: c and any(
                kw in c for kw in ['job-card', 'job_card', 'listing', 'vacancy', 'position']
            ))
            
            content_text = ""
            if not job_cards:
                seen = set()
                for a in soup.find_all('a', href=True):
                    href = a.get('href', '')
                    if 'facebook.com/sharer' in href and '?u=' in href:
                        href = urllib.parse.unquote(href.split('?u=')[1].split('&')[0])
                    elif 'twitter.com/intent/tweet' in href and 'url=' in href:
                        href = urllib.parse.unquote(href.split('url=')[1].split('&')[0])
                    elif 'linkedin.com/share' in href and 'url=' in href:
                        href = urllib.parse.unquote(href.split('url=')[1].split('&')[0])
                    if not ('/job' in href or '/vacancy' in href or '/position' in href):
                        continue
                    if href.startswith('/'):
                        href = "https://egypt.tanqeeb.com" + href
                    if href in seen:
                        continue
                    seen.add(href)
                    if is_job_seen(href):
                        logging.debug(f"    ⏭️ Skipping known job (cached): {href}")
                        continue
                    card = a.find_parent(['li', 'article', 'div'])
                    card_text = card.get_text(separator=' ', strip=True) if card else a.get_text(strip=True)
                    if len(card_text) > 10:
                        content_text += f"Job Link: {href}\nJob Info: {card_text}\n\n"
            else:
                for card in job_cards:
                    href = ""
                    for a in card.find_all('a', href=True):
                        link_href = a.get('href', '')
                        if 'facebook.com/sharer' in link_href and '?u=' in link_href:
                            link_href = urllib.parse.unquote(link_href.split('?u=')[1].split('&')[0])
                        elif 'twitter.com/intent/tweet' in link_href and 'url=' in link_href:
                            link_href = urllib.parse.unquote(link_href.split('url=')[1].split('&')[0])
                        elif 'linkedin.com/share' in link_href and 'url=' in link_href:
                            link_href = urllib.parse.unquote(link_href.split('url=')[1].split('&')[0])
                            
                        if '/job' in link_href or '/vacancy' in link_href or link_href.startswith('/'):
                            href = link_href
                            break
                            
                    if not href:
                        continue
                    
                    if href.startswith('/'):
                        href = "https://egypt.tanqeeb.com" + href
                    if is_job_seen(href):
                        logging.debug(f"    ⏭️ Skipping known job (cached): {href}")
                        continue
                    card_text = card.get_text(separator=' ', strip=True)
                    content_text += f"Job Link: {href}\nJob Info: {card_text}\n\n"

            if not content_text.strip():
                break  # No jobs found on this page
                
            content_text = content_text[:20000]
            ai_data = extract_feed_posts_with_ai(content_text)
            
            if ai_data and not ai_data.get("error"):
                jobs_list = ai_data.get("jobs", [])
                if not jobs_list:
                    break  # AI extracted no jobs
                    
                added_in_page = 0
                too_old_count = 0
                for job in jobs_list:
                    if job.get("is_job"):
                        # Check date limit
                        date_posted_str = job.get('date_posted')
                        job_date = None
                        is_too_old = False
                        if date_posted_str:
                            try:
                                job_date = datetime.datetime.strptime(date_posted_str, "%Y-%m-%d").date()
                                days_old = (datetime.date.today() - job_date).days
                                if hours_old and (days_old * 24) > hours_old:
                                    is_too_old = True
                            except Exception:
                                pass
                        
                        if is_too_old:
                            too_old_count += 1
                            continue
                            
                        if len(jobs) < results_wanted:
                            job_url = job.get('job_url', '')
                            if not job_url:
                                job_url = url
                                
                            jobs.append({
                                'title': job.get('title', 'Unknown'),
                                'company': job.get('company', 'Unknown'),
                                'location': job.get('location', location),
                                'job_url': job_url,
                                'job_type': job.get('job_type', 'Not specified'),
                                'description': job.get('description', ''),
                                'is_remote': 'remote' in search_term.lower() or 'remote' in str(job.get('location', '')).lower(),
                                'site': 'tanqeeb',
                                'date_posted': job_date or datetime.datetime.now().date()
                            })
                            added_in_page += 1
                
                # If everything found is too old, stop paginating
                if too_old_count == len(jobs_list) and len(jobs_list) > 0:
                    break
                    
                # If we parsed jobs but added none (meaning all duplicates or skipped), check next page
                if added_in_page == 0:
                    break
            else:
                logging.warning(f"⚠️ Tanqeeb AI Parsing Error: {ai_data.get('error') if ai_data else 'Unknown'}")
                break
                
        except Exception as e:
            logging.error(f"⚠️ Tanqeeb Scraper Error: {e}")
            break
            
        page += 1
        time.sleep(1.5)
        
    return pd.DataFrame(jobs)

if __name__ == "__main__":
    print("Testing Tanqeeb Scraper...")
    df = scrape_tanqeeb("software engineer", "egypt", 5)
    print(df.head())
