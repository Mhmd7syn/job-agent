import requests
import urllib.parse
from bs4 import BeautifulSoup
import pandas as pd
import time
import re
import datetime
import logging
import random

def fetch_wuzzuf_full_description(job_url, driver=None):
    """Fetches the complete full job description and requirements from a Wuzzuf job detail page."""
    if not job_url:
        return ""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        resp = requests.get(job_url, headers=headers, timeout=6)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.content, 'html.parser')
            sections = soup.find_all(['section', 'div'], class_=lambda c: c and any(k in str(c) for k in ['css-3fx252', 'css-1u1fu21', 'css-117ic1a', 'description', 'requirements']))
            if sections:
                full_text = "\n\n".join([sec.get_text(separator=' ', strip=True) for sec in sections if len(sec.get_text(strip=True)) > 20])
                if len(full_text) > 80:
                    return full_text
            req_sec = soup.find('section', class_=lambda c: c and 'css-1v1k5x' in c) or soup.find('div', class_=lambda c: c and 'css-10p02e' in c)
            if req_sec:
                return req_sec.get_text(separator=' ', strip=True)
    except Exception as e:
        logging.debug(f"Wuzzuf requests fetch failed for {job_url}: {e}")

    if driver:
        try:
            driver.uc_open_with_reconnect(job_url, 3)
            soup = BeautifulSoup(driver.get_page_source(), 'html.parser')
            sections = soup.find_all(['section', 'div'], class_=lambda c: c and any(k in str(c) for k in ['css-3fx252', 'css-1u1fu21', 'css-117ic1a', 'description', 'requirements']))
            if sections:
                return "\n\n".join([sec.get_text(separator=' ', strip=True) for sec in sections if len(sec.get_text(strip=True)) > 20])
        except Exception as e:
            logging.debug(f"Wuzzuf driver fallback failed for {job_url}: {e}")

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
        except Exception:
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

            _JOB_TYPE_KWS = {'full time', 'part time', 'freelance', 'contract', 'remote', 'work from home', 'internship', 'student activity'}
            _CAREER_LEVEL_KWS = {'fresh graduate', 'junior', 'mid level', 'mid-level', 'senior', 'manager',
                                  'director', 'executive', 'student activity', 'entry level', 'entry-level',
                                  'experienced', 'team lead', 'c-level', 'vp'}
            type_tags = [t for t in all_tags if any(k in t.lower() for k in _JOB_TYPE_KWS)]
            level_tags = [t for t in all_tags if any(k in t.lower() for k in _CAREER_LEVEL_KWS)]

            job_type = ", ".join(type_tags) if type_tags else "Full Time"
            career_level = ", ".join(level_tags) if level_tags else "Not specified"

            card_desc = card.get_text(separator=' ', strip=True)
            full_desc = fetch_wuzzuf_full_description(job_url, driver=driver)
            description = full_desc if full_desc and len(full_desc) > len(card_desc) else card_desc

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
