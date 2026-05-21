import pandas as pd
from jobspy import scrape_jobs
import sys
import time
import random
import html

from config import *
from wuzzuf_scraper import scrape_wuzzuf
from telegram_notifier import send_telegram_message

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
    print("🤖 Starting the JobSpy Agent...")
    
    jobs_list = []
    
    for term in SEARCH_TERMS:
        for loc in LOCATION:
            print(f"🔍 Scraping for: '{term}' in {loc}...")
            try:
                is_remote_flag = False
                search_loc = loc
                if loc.lower() == "remote":
                    search_loc = "worldwide"
                    is_remote_flag = True
                    
                jobs = None
                for attempt in range(3): # Auto-Retries for Network Errors
                    try:
                        jobs = scrape_jobs(
                            site_name=SITES,
                            search_term=term,
                            location=search_loc,
                            is_remote=is_remote_flag,
                            results_wanted=RESULTS_PER_TERM,
                            hours_old=HOURS_OLD,
                        )
                        break
                    except Exception as e:
                        print(f"⚠️ Retry {attempt+1}/3 for scrape_jobs failed: {e}")
                        time.sleep(3)
                        
                if jobs is not None and not jobs.empty:
                    jobs_list.append(jobs)
                    
                if USE_WUZZUF:
                    wuzzuf_jobs = scrape_wuzzuf(term, loc, RESULTS_PER_TERM)
                    if wuzzuf_jobs is not None and not wuzzuf_jobs.empty:
                        jobs_list.append(wuzzuf_jobs)
                    
            except Exception as e:
                print(f"⚠️ Error scraping '{term}' in {loc}: {e}")
            
            delay = random.uniform(3, 7)
            print(f"⏳ Sleeping for {delay:.2f} seconds to avoid rate limits...")
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
    
    print("🧠 Scoring jobs based on relevance to your search terms...")
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

    print("🧹 Preparing final jobs list...")
    filtered_jobs = all_jobs
    
    if not filtered_jobs.empty:
        sort_cols = ['relevance_score']
        ascending_flags = [False]
        if 'date_posted' in filtered_jobs.columns:
            sort_cols.append('date_posted')
            ascending_flags.append(False)
            
        filtered_jobs = filtered_jobs.sort_values(by=sort_cols, ascending=ascending_flags)
        
    print(f"🎯 Found {len(filtered_jobs)} matching jobs out of {len(all_jobs)} scraped.")

    # --- STATE MANAGEMENT (Prevent Duplicate Alerts) ---
    import os
    import json
    import datetime
    
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
        print(f"📬 After removing previously sent jobs, {len(filtered_jobs)} remain.")

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