import requests
import urllib.parse
from bs4 import BeautifulSoup
import pandas as pd
import time
import re
import datetime
import logging
import random

# Per-job description fetch removed: card-level text is sufficient for scoring
# and avoids ~210 extra HTTP requests + 315 s of mandatory sleep per run.

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

def scrape_wuzzuf(search_term, location, results_wanted=15, hours_old=None, driver=None):
    jobs = []
    query = search_term
    if location.lower() == "worldwide" or location.lower() == "remote":
        query += " remote"
        
    url = f"https://wuzzuf.net/search/jobs/?q={urllib.parse.quote(query)}&o=t"
    if hours_old:
        days = hours_old / 24
        if days <= 1:
            url += "&filters[post_date][0]=within_24_hours"
        elif days <= 7:
            url += "&filters[post_date][0]=within_1_week"
        else:
            url += "&filters[post_date][0]=within_1_month"
    
    if driver is None:
        logging.error("Wuzzuf scraper requires a SeleniumBase driver.")
        return pd.DataFrame()
        
    try:
        driver.uc_open_with_reconnect(url, 4)
        try:
            driver.uc_gui_click_captcha()
        except Exception:
            pass
        
        try:
            driver.wait_for_element('div.css-pkv5jc', timeout=10)
        except:
            driver.save_screenshot("wuzzuf.png")
            pass

        html_content = driver.get_page_source()
        soup = BeautifulSoup(html_content, 'html.parser')
        job_cards = soup.find_all('div', class_=lambda c: c and 'css-pkv5jc' in c)
        
        for card in job_cards:
            if len(jobs) >= results_wanted:
                break
                
            title_tag = card.find('h2')
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
            all_tags = [t.text.strip() for t in job_type_tags]

            # Wuzzuf mixes job-type and career-level in the same span tags — split them
            _JOB_TYPE_KWS = {'full time', 'part time', 'freelance', 'contract', 'remote', 'work from home', 'internship', 'student activity'}
            _CAREER_LEVEL_KWS = {'fresh graduate', 'junior', 'mid level', 'mid-level', 'senior', 'manager',
                                  'director', 'executive', 'student activity', 'entry level', 'entry-level',
                                  'experienced', 'team lead', 'c-level', 'vp'}
            type_tags = [t for t in all_tags if any(k in t.lower() for k in _JOB_TYPE_KWS)]
            level_tags = [t for t in all_tags if any(k in t.lower() for k in _CAREER_LEVEL_KWS)]

            job_type = ", ".join(type_tags) if type_tags else "Full Time"
            career_level = ", ".join(level_tags) if level_tags else "Not specified"

            # Use card text as description (avoids per-job HTTP fetch)
            description = card.get_text(separator=' ', strip=True)

            jobs.append({
                'title': title,
                'company': company,
                'location': loc,
                'job_url': job_url,
                'job_type': job_type,
                'career_level': career_level,
                'description': description,
                'is_remote': 'remote' in query.lower() or any('remote' in t.lower() or 'work from home' in t.lower() for t in all_tags),
                'site': 'wuzzuf',
                'date_posted': date_posted.date()
            })
            
    except Exception as e:
        logging.error(f"⚠️ Wuzzuf Scraper Error: {e}")
        
    return pd.DataFrame(jobs)
