import pandas as pd
from jobspy import scrape_jobs
import sys
import time
import random
import html

from config import *
from wuzzuf_scraper import scrape_wuzzuf
from telegram_notifier import send_telegram_message

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
                    
                jobs = scrape_jobs(
                    site_name=SITES,
                    search_term=term,
                    location=search_loc,
                    is_remote=is_remote_flag,
                    results_wanted=RESULTS_PER_TERM,
                    hours_old=HOURS_OLD,
                )
                if jobs is not None and not jobs.empty:
                    jobs_list.append(jobs)
                    
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

    all_jobs = pd.concat(jobs_list, ignore_index=True)

    all_jobs = all_jobs.drop_duplicates(subset=["job_url"])
    
    all_jobs['description'] = all_jobs['description'].fillna("")
    all_jobs['title'] = all_jobs['title'].fillna("")
    all_jobs['company'] = all_jobs['company'].fillna("")
    
    def location_filter(row):
        loc_val = str(row.get('location', '')).lower()
        title_val = str(row.get('title', '')).lower()
        is_remote_col = row.get('is_remote', False)
        
        is_remote = False
        allow_remote = any('remote' in l.lower() for l in LOCATION)
        if allow_remote:
            is_remote = (is_remote_col == True) or ('remote' in loc_val) or ('remote' in title_val)
            
        if FILTER_BY_SPECIFIC_LOCATIONS:
            is_in_target = any(target in loc_val for target in TARGET_LOCATIONS)
        else:
            is_in_target = True
            
        return is_remote or is_in_target

    if not all_jobs.empty:
        all_jobs = all_jobs[all_jobs.apply(location_filter, axis=1)]
        
    if FILTER_BY_LEVEL and not all_jobs.empty:
        def level_filter(row):
            title_val = str(row.get('title', '')).lower()
            job_type_val = str(row.get('job_type', '')).lower()
            return any(level in title_val or level in job_type_val for level in TARGET_LEVELS)
            
        all_jobs = all_jobs[all_jobs.apply(level_filter, axis=1)]
    
    if not all_jobs.empty:
        all_jobs['title_company_lower'] = all_jobs['title'].str.lower() + " " + all_jobs['company'].str.lower()
        all_jobs = all_jobs.drop_duplicates(subset=["title_company_lower"])
        all_jobs = all_jobs.drop(columns=["title_company_lower"])
    
    print("🧹 Filtering jobs based on requirements...")
    
    if USE_KEYWORD_FILTER:
        def contains_keywords(row):
            text_to_search = (row['title'] + " " + row['description']).lower()
            return any(keyword.lower() in text_to_search for keyword in MUST_HAVE_KEYWORDS)

        filtered_jobs = all_jobs[all_jobs.apply(contains_keywords, axis=1)]
    else:
        filtered_jobs = all_jobs
    
    if 'date_posted' in filtered_jobs.columns:
        filtered_jobs = filtered_jobs.sort_values(by="date_posted", ascending=False)
        
    print(f"🎯 Found {len(filtered_jobs)} matching jobs out of {len(all_jobs)} scraped.")

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

if __name__ == "__main__":
    main()