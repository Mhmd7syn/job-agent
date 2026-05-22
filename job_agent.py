import pandas as pd
from jobspy import scrape_jobs
import sys
import time
import random
import html
import glob
import os
import json
import datetime
import logging

logging.basicConfig(level=logging.WARNING)

# Suppress all JobSpy loggers
for name in logging.Logger.manager.loggerDict.keys():
    if name.startswith("JobSpy"):
        logging.getLogger(name).setLevel(logging.WARNING)

from config import *

from wuzzuf_scraper import scrape_wuzzuf
from telegram_notifier import send_telegram_message
try:
    from playwright_scraper import get_posts_as_dataframe
except ImportError:
    get_posts_as_dataframe = None

# Monkey-patch jobspy's Country.from_string to avoid crashing on unknown countries (e.g. Albania)
from jobspy.model import Country

original_from_string = Country.from_string

@classmethod
def patched_from_string(cls, country_str: str):
    try:
        return original_from_string(country_str)
    except ValueError:
        return country_str

Country.from_string = patched_from_string

if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

def main():

    
    jobs_list = []
    
    for term in SEARCH_TERMS:
        for loc in LOCATION:

            try:
                is_remote_flag = False
                search_loc = loc
                if loc.lower() == "remote":
                    search_loc = "worldwide"
                    is_remote_flag = True
                    
                jobs = None
                if SITES:
                    for attempt in range(3): # Auto-Retries for Network Errors
                        try:
                            jobs = scrape_jobs(
                                site_name=SITES,
                                search_term=term,
                                location=search_loc,
                                results_wanted=RESULTS_PER_TERM,
                                hours_old=HOURS_OLD,
                                linkedin_fetch_description=True
                            )
                            break

                        except Exception as e:
                            print(f"⚠️ Retry {attempt+1}/3 for scrape_jobs failed: {e}")
                            time.sleep(3)
                        
                if jobs is not None and not jobs.empty:
                    jobs_list.append(jobs)
                    
                if USE_WUZZUF:
                    wuzzuf_jobs = scrape_wuzzuf(term, loc, RESULTS_PER_TERM, HOURS_OLD)
                    if wuzzuf_jobs is not None and not wuzzuf_jobs.empty:
                        jobs_list.append(wuzzuf_jobs)
                        
                if SCRAPE_LINKEDIN_POSTS and get_posts_as_dataframe:
                    try:
                        post_jobs = get_posts_as_dataframe(term, loc)
                        if post_jobs is not None and not post_jobs.empty:
                            jobs_list.append(post_jobs)
                    except Exception as e:
                        print(f"⚠️ Error scraping posts for '{term}' in {loc}: {e}")
                    
            except Exception as e:
                print(f"⚠️ Error scraping '{term}' in {loc}: {e}")
            
            delay = random.uniform(3, 7)
            time.sleep(delay)

            
    if not jobs_list:
        print("No jobs found across any platform.")
        return

    cleaned_jobs_list = [df.dropna(axis=1, how='all') for df in jobs_list if not df.empty]
    if not cleaned_jobs_list:
        print("No jobs found across any platform.")
        return
        
    all_jobs = pd.concat(cleaned_jobs_list, ignore_index=True)

    all_jobs = all_jobs.drop_duplicates(subset=["job_url"])
    
    all_jobs['description'] = all_jobs['description'].fillna("")
    all_jobs['title'] = all_jobs['title'].fillna("")
    all_jobs['company'] = all_jobs['company'].fillna("")
    
    if not all_jobs.empty:
        all_jobs['title_company_lower'] = all_jobs['title'].str.lower() + " " + all_jobs['company'].str.lower()
        all_jobs = all_jobs.drop_duplicates(subset=["title_company_lower"])
        all_jobs = all_jobs.drop(columns=["title_company_lower"])
        
        # Ensure is_remote is correctly flagged
        def fix_is_remote(row):
            if row.get('is_remote') == True:
                return True
            if any('remote' in str(row.get(col, '')).lower() for col in ['location', 'title', 'job_type']):
                return True
            return False
        all_jobs['is_remote'] = all_jobs.apply(fix_is_remote, axis=1)

    
    import re

    from datetime import date
    def get_relevance_score(row):
        title = str(row.get('title', '')).lower()
        desc = str(row.get('description', '')).lower()
        company = str(row.get('company', '')).lower()
        score = 0
        
        # 1. Negative Filtering: Instant drop for unwanted keywords or spammy companies
        if any(kw in title for kw in EXCLUDE_KEYWORDS) or any(kw in title.split() for kw in EXCLUDE_KEYWORDS):
            return -100
            
        if any(comp in company for comp in EXCLUDED_COMPANIES):
            return -100
            
        # 2. Company Whitelist Boost
        if any(comp in company for comp in FAVORITE_COMPANIES):
            score += 15
            
        for term in SEARCH_TERMS:
            term_lower = term.lower()
            if term_lower in title:
                score += 10
            elif term_lower in desc:
                score += 3
                
        # 3. Resume Match Scoring (High priority)
        for kw in RESUME_KEYWORDS:
            pattern = r'\b' + re.escape(kw) + r'\b'
            if re.search(pattern, title):
                score += 5  # Higher bonus for hitting a resume skill in the title
            elif re.search(pattern, desc):
                score += 2  # Standard bonus for being in the description
                
        # 4. Nice-to-Have Skills (Medium priority)
        for kw in NICE_TO_HAVE_SKILLS:
            pattern = r'\b' + re.escape(kw) + r'\b'
            if re.search(pattern, title):
                score += 3
            elif re.search(pattern, desc):
                score += 1
                
        # Score locations
        loc_val = str(row.get('location', '')).lower()
        is_remote_col = row.get('is_remote', False)
        
        allow_remote = any('remote' in l.lower() for l in LOCATION)
        if allow_remote and ((is_remote_col == True) or ('remote' in loc_val) or ('remote' in title)):
            score += 5
            
        if any(target in loc_val for target in TARGET_LOCATIONS):
            score += 5
            
        # Score levels
        job_type_val = str(row.get('job_type', '')).lower()
        if any(level in title or level in job_type_val for level in TARGET_LEVELS):
            score += 5
            
        # 4. Recency Boost
        post_date = row.get('date_posted')
        if pd.notna(post_date):
            try:
                if hasattr(post_date, 'date'):
                    p_date = post_date.date()
                else:
                    p_date = pd.to_datetime(post_date).date()
                
                days_old = (date.today() - p_date).days
                if days_old == 0:
                    score += 15
                elif days_old == 1:
                    score += 7
                elif days_old > 5:
                    score -= 5
            except Exception:
                pass
                
        return score

    if not all_jobs.empty:
        all_jobs['relevance_score'] = all_jobs.apply(get_relevance_score, axis=1)
        # Filter out jobs that don't match any of our keywords or search terms
        all_jobs = all_jobs[all_jobs['relevance_score'] > 0]

    filtered_jobs = all_jobs

    
    if not filtered_jobs.empty:
        sort_cols = ['relevance_score']
        ascending_flags = [False]
        if 'date_posted' in filtered_jobs.columns:
            sort_cols.append('date_posted')
            ascending_flags.append(False)
            
        filtered_jobs = filtered_jobs.sort_values(by=sort_cols, ascending=ascending_flags)
        




    # Save the best 100 found jobs after reranking
    if not filtered_jobs.empty:
        best_100 = filtered_jobs.head(100).copy()
        if 'description' in best_100.columns:
            best_100 = best_100.drop(columns=['description'])
            
        current_date_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"found_jobs_{current_date_str}.csv"
        best_100.to_csv(filename, index=False)

        # Delete found_jobs files older than 30 days

        thirty_days_ago = time.time() - (30 * 24 * 60 * 60)
        for f in glob.glob("found_jobs_*.csv"):
            try:
                if os.path.getmtime(f) < thirty_days_ago:
                    os.remove(f)
            except Exception as e:

                print(f"⚠️ Failed to delete old job file {f}: {e}")

    # --- STATE MANAGEMENT (Prevent Duplicate Alerts) ---
    
    STATE_FILE = "sent_jobs.json"
    sent_jobs = {}
    
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
                if isinstance(data, list):
                    # Migration from old format to new format
                    sent_jobs = {}
                else:
                    sent_jobs = data
        except Exception:
            pass
            
    # Remove jobs older than 45 days so they can be re-applied if reopened
    current_time = datetime.datetime.now()
    jobs_to_keep = {}
    for job_id, date_str in sent_jobs.items():
        try:
            job_date = datetime.datetime.fromisoformat(date_str)
            if (current_time - job_date).days <= 45:
                jobs_to_keep[job_id] = date_str
        except:
            pass
    sent_jobs = jobs_to_keep
            
    # Filter out already sent jobs using title and company
    if not filtered_jobs.empty:
        # Create an ID column for checking
        filtered_jobs['job_id'] = filtered_jobs['title'].str.lower().str.strip() + " " + filtered_jobs['company'].str.lower().str.strip()
        filtered_jobs = filtered_jobs[~filtered_jobs['job_id'].isin(sent_jobs.keys())]

    if filtered_jobs.empty:

        send_telegram_message("📉 <b>Job Agent Report</b>\nNo new jobs matched your specific keywords this week.")
        return

    top_jobs = filtered_jobs.head(MAX_JOBS_TO_SEND)
    
    message = f"🚀 <b>Weekly Job Agent Report</b>\n<i>Found {len(filtered_jobs)} matches. Here are the top picks:</i>\n\n"
    
    for index, row in top_jobs.iterrows():
        title = html.escape(str(row['title']))
        company = html.escape(str(row['company']))
        location = html.escape(str(row.get('location', 'Location N/A')))
        
        job_type = str(row.get('job_type', 'Not specified')).title()
        if job_type.lower() == 'nan' or not job_type.strip():
            job_type = 'Not specified'
            
        link = row['job_url']
        
        message += f"💼 <b>{title}</b>\n"
        message += f"🏢 {company} | 📍 {location}\n"
        message += f"⏱️ Type: {html.escape(job_type)}\n"
        message += f"🔗 <a href='{link}'>Apply Here</a>\n"
        message += "━━━━━━━━━━━━━━━━━━━━\n"
        
    send_telegram_message(message)
    
    # Save the new jobs back to the state file
    for index, row in top_jobs.iterrows():
        job_id = (str(row['title']).lower().strip() + " " + str(row['company']).lower().strip())
        sent_jobs[job_id] = current_time.isoformat()
        
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(sent_jobs, f, indent=4)
    except Exception as e:
        print(f"⚠️ Failed to save state file: {e}")

if __name__ == "__main__":
    main()