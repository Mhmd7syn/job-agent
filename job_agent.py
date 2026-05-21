import pandas as pd
import requests
from jobspy import scrape_jobs
import sys
import time
import random
import html

if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

TELEGRAM_BOT_TOKEN = "8890636648:AAF7zcc8VKpe3XLDiEjPefhr0NGFvV2MgFc"
TELEGRAM_CHAT_ID = "6431446621"

SEARCH_TERMS = [
    "AI Engineer", "Machine Learning Engineer", "Artificial Intelligence",
    "Data Scientist", "Data Science", 
    "Data Analyst", "Data Analysis",
    "AI Instructor", "Data Science Instructor", "Machine Learning Instructor", "Data Analytics Instructor", "Python Instructor", "Programming Instructor", "Coding Instructor"
]
USE_KEYWORD_FILTER = False
MUST_HAVE_KEYWORDS = ["pytorch", "tensorflow", "yolo", "mediapipe", "python", "computer vision", "deep learning"]

LOCATION = ["Remote", "Egypt"]
FILTER_BY_SPECIFIC_LOCATIONS = False
TARGET_LOCATIONS = [
    "cairo", "giza", "new capital", "administrative capital", 
    "maadi", "masr el gedida", "heliopolis", "nasr city", 
    "new cairo", "tagamoa", "6th of october", "october", 
    "sheikh zayed", "zayed", "shorouk", "obour", "badr", "10th of ramadan",
    "smart village"
]

FILTER_BY_LEVEL = True
TARGET_LEVELS = ["junior", "fresh", "student", "intern", "entry"]

SITES = ["linkedin", "indeed", "glassdoor", "bayt", "google"]
RESULTS_PER_TERM = 15
HOURS_OLD = 7 * 24
MAX_JOBS_TO_SEND = 10

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    
    response = requests.post(url, json=payload)
    if response.status_code == 200:
        print("✅ Message successfully sent to Telegram.")
    else:
        print(f"❌ Failed to send message. Error: {response.text}")

def main():
    print("🤖 Starting the JobSpy Agent...")
    
    all_jobs = pd.DataFrame()
    
    for term in SEARCH_TERMS:
        for loc in LOCATION:
            print(f"🔍 Scraping for: '{term}' in {loc}...")
            try:
                jobs = scrape_jobs(
                    site_name=SITES,
                    search_term=term,
                    location=loc,
                    results_wanted=RESULTS_PER_TERM,
                    hours_old=HOURS_OLD,
                )
                all_jobs = pd.concat([all_jobs, jobs], ignore_index=True)
            except Exception as e:
                print(f"⚠️ Error scraping '{term}' in {loc}: {e}")
            
            delay = random.uniform(3, 7)
            print(f"⏳ Sleeping for {delay:.2f} seconds to avoid rate limits...")
            time.sleep(delay)
            
    if all_jobs.empty:
        print("No jobs found across any platform.")
        return

    all_jobs = all_jobs.drop_duplicates(subset=["job_url"])
    
    all_jobs['description'] = all_jobs['description'].fillna("")
    all_jobs['title'] = all_jobs['title'].fillna("")
    all_jobs['company'] = all_jobs['company'].fillna("")
    
    def location_filter(row):
        loc = str(row.get('location', '')).lower()
        title = str(row.get('title', '')).lower()
        is_remote_col = row.get('is_remote', False)
        
        is_remote = False
        allow_remote = any('remote' in l.lower() for l in LOCATION)
        if allow_remote:
            is_remote = (is_remote_col == True) or ('remote' in loc) or ('remote' in title)
            
        if FILTER_BY_SPECIFIC_LOCATIONS:
            is_in_target = any(target in loc for target in TARGET_LOCATIONS)
        else:
            is_in_target = True
            
        return is_remote or is_in_target

    if not all_jobs.empty:
        all_jobs = all_jobs[all_jobs.apply(location_filter, axis=1)]
        
    if FILTER_BY_LEVEL and not all_jobs.empty:
        def level_filter(row):
            title = str(row.get('title', '')).lower()
            job_type = str(row.get('job_type', '')).lower()
            # If the job explicitly states it's one of these levels in the title or job_type
            return any(level in title or level in job_type for level in TARGET_LEVELS)
            
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
        
        # Format the job type nicely (e.g. "fulltime" -> "Fulltime")
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