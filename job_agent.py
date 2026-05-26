import pandas as pd
import sys
import time
import random
import html
import glob
import os
import json
import datetime
import logging
import ctypes

def prevent_sleep():
    """Prevent the Windows OS from going to sleep while the script runs."""
    if os.name == 'nt':
        # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)

def allow_sleep():
    """Allow the Windows OS to go to sleep again."""
    if os.name == 'nt':
        # ES_CONTINUOUS
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)

class RootFilter(logging.Filter):
    def filter(self, record):
        return record.name == 'root'

# Configure logging to save to file with timestamps, but print to terminal cleanly
file_handler = logging.FileHandler("job_agent.log", mode="w", encoding="utf-8")
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
file_handler.addFilter(RootFilter())

console_handler = logging.StreamHandler(sys.stdout) 
console_handler.setFormatter(logging.Formatter('%(message)s'))
console_handler.addFilter(RootFilter())

logging.basicConfig(    
    level=logging.WARNING,
    handlers=[file_handler, console_handler]
)


from config import *

from wuzzuf_scraper import scrape_wuzzuf
from tanqeeb_scraper import scrape_tanqeeb
from bayt_scraper import scrape_bayt
from glassdoor_scraper import scrape_glassdoor
from telegram_notifier import send_telegram_message
try:
    from playwright_scraper import get_posts_as_dataframe, scrape_linkedin_jobs_playwright
except ImportError:
    get_posts_as_dataframe = None
    scrape_linkedin_jobs_playwright = None


if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

def main():

    
    import concurrent.futures
    from tqdm import tqdm
    jobs_list = []
    
    def retry_scraper(scraper_func, *args, max_retries=2):
        for attempt in range(max_retries + 1):
            try:
                return scraper_func(*args)
            except Exception as e:
                if attempt < max_retries:
                    wait_time = 2 ** attempt
                    logging.warning(f"⚠️ Retrying {scraper_func.__name__} after error: {e}. Waiting {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    logging.error(f"❌ Final failure for {scraper_func.__name__}: {e}")
                    return None

    def run_scrapers_for_term_loc(term, loc):
        local_jobs_list = []
        is_remote_flag = False
        search_loc = loc
        if loc.lower() == "remote":
            search_loc = "worldwide"
            is_remote_flag = True

        futures = []
        # Use ThreadPoolExecutor to run non-Playwright scrapers in the background
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            if 'wuzzuf' in [s.lower() for s in SITES]:
                futures.append(executor.submit(retry_scraper, scrape_wuzzuf, term, loc, RESULTS_PER_TERM, HOURS_OLD))
            if 'tanqeeb' in [s.lower() for s in SITES]:
                futures.append(executor.submit(retry_scraper, scrape_tanqeeb, term, loc, RESULTS_PER_TERM, HOURS_OLD))
            if 'bayt' in [s.lower() for s in SITES]:
                futures.append(executor.submit(retry_scraper, scrape_bayt, term, loc, RESULTS_PER_TERM, HOURS_OLD))
            if 'glassdoor' in [s.lower() for s in SITES]:
                futures.append(executor.submit(retry_scraper, scrape_glassdoor, term, loc, RESULTS_PER_TERM, HOURS_OLD))
            if 'indeed' in [s.lower() for s in SITES]:
                try:
                    from indeed_scraper import scrape_indeed
                    futures.append(executor.submit(retry_scraper, scrape_indeed, term, loc, RESULTS_PER_TERM, HOURS_OLD))
                except ImportError:
                    pass

            # Run Playwright tasks sequentially in the main thread while background threads run the rest!
            if 'linkedin' in [s.lower() for s in SITES]:
                if scrape_linkedin_jobs_playwright:
                    try:
                        res = retry_scraper(scrape_linkedin_jobs_playwright, term, search_loc, RESULTS_PER_TERM, HOURS_OLD)
                        if res is not None and not res.empty:
                            local_jobs_list.append(res)
                    except Exception as e:
                        logging.error(f"⚠️ Playwright jobs failure: {e}")
                if get_posts_as_dataframe:
                    try:
                        res = retry_scraper(get_posts_as_dataframe, term, loc)
                        if res is not None and not res.empty:
                            local_jobs_list.append(res)
                    except Exception as e:
                        logging.error(f"⚠️ Playwright posts failure: {e}")

            # Collect results from the background threads
            for future in concurrent.futures.as_completed(futures):
                try:
                    result = future.result()
                    if result is not None and not result.empty:
                        local_jobs_list.append(result)
                except Exception as e:
                    logging.error(f"⚠️ Thread failure: {e}")
                    
        return local_jobs_list

    total_iterations = len(SEARCH_TERMS) * len(LOCATION)
    with tqdm(total=total_iterations, desc="Scraping Jobs", unit="search") as pbar:
        for term in SEARCH_TERMS:
            for loc in LOCATION:
                try:
                    local_results = run_scrapers_for_term_loc(term, loc)
                    jobs_list.extend(local_results)
                except Exception as e:
                    logging.error(f"⚠️ Error in term/loc loop '{term}' in {loc}: {e}")
                
                delay = random.uniform(3, 7)
                time.sleep(delay)
                pbar.update(1)

            
    if not jobs_list:
        logging.info("No jobs found across any platform.")
        return

    cleaned_jobs_list = [df.dropna(axis=1, how='all') for df in jobs_list if not df.empty]
    if not cleaned_jobs_list:
        logging.info("No jobs found across any platform.")
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
        
        # LinkedIn descriptions are now accurately fetched directly during the Playwright search phase.
        
        # Ensure is_remote is correctly flagged
        def fix_is_remote(row):
            if row.get('is_remote') == True:
                return True
            if any('remote' in str(row.get(col, '')).lower() for col in ['location', 'title', 'job_type']):
                return True
            return False
        all_jobs['is_remote'] = all_jobs.apply(fix_is_remote, axis=1)

        def fix_job_type(row):
            job_type = str(row.get('job_type', '')).lower()
            title_desc = str(row.get('title', '')).lower() + ' ' + str(row.get('description', '')).lower()
            if job_type in ['nan', 'not specified', '']:
                if any(kw in title_desc for kw in ['intern', 'internship', 'trainee', 'working student']):
                    return 'Internship'
                elif any(kw in title_desc for kw in ['part time', 'part-time']):
                    return 'Part-time'
                elif any(kw in title_desc for kw in ['full time', 'full-time']):
                    return 'Full-time'
                return 'Not specified'
            return str(row.get('job_type', 'Not specified')).title()
            
        all_jobs['job_type'] = all_jobs.apply(fix_job_type, axis=1)

    
    import re

    from datetime import date
    def get_relevance_score(row):
        title = str(row.get('title', '')).lower()
        desc = str(row.get('description', '')).lower()
        company = str(row.get('company', '')).lower()
        score = 0
        
        # 1. Negative Filtering: Penalize for unwanted keywords
        for kw in EXCLUDE_KEYWORDS:
            if kw in title or kw in title.split():
                score -= 50
                
        # Instant drop for spammy companies
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
                
            matches = len(re.findall(pattern, desc))
            if matches > 0:
                score += min(matches * 2, 8)  # Max +8 per skill in description
                
        # 4. Nice-to-Have Skills (Medium priority)
        for kw in NICE_TO_HAVE_SKILLS:
            pattern = r'\b' + re.escape(kw) + r'\b'
            if re.search(pattern, title):
                score += 3
                
            matches = len(re.findall(pattern, desc))
            if matches > 0:
                score += min(matches * 1, 3)  # Max +3 per skill in description
                
        # Score locations
        loc_val = str(row.get('location', '')).lower()
        is_remote_col = row.get('is_remote', False)
        

        allow_remote = any('remote' in l.lower() for l in LOCATION)
        if allow_remote and ((is_remote_col == True) or ('remote' in loc_val) or ('remote' in title)):
            score += 5
            title_desc = title + " " + desc
            if any(r in title_desc for r in GLOBAL_REMOTE_KEYWORDS):
                score += 5
            if any(r in title_desc for r in RESTRICTED_REMOTE_KEYWORDS):
                score -= 30
            
        if any(target in loc_val for target in TARGET_LOCATIONS):
            score += 5
            
        # Score levels
        job_type_val = str(row.get('job_type', '')).lower()
        if any(level in title or level in job_type_val or level in desc for level in TARGET_LEVELS):
            score += 15
            
        # 4. Recency Boost
        post_date = row.get('date_posted')
        if pd.notna(post_date):
            try:
                if hasattr(post_date, 'date'):
                    p_date = post_date.date()
                else:
                    p_date = pd.to_datetime(post_date).date()
                
                days_old = (date.today() - p_date).days

                if HOURS_OLD > 0:
                    hours_old_calc = days_old * 24
                    freshness_ratio = 1.0 - (hours_old_calc / HOURS_OLD)
                    score += int(15 * freshness_ratio)
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

                logging.warning(f"⚠️ Failed to delete old job file {f}: {e}")

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
            
        link = str(row.get('job_url', '')).strip()
        
        message += f"💼 <b>{title}</b>\n"
        message += f"🏢 {company} | 📍 {location}\n"
        message += f"⏱️ Type: {html.escape(job_type)}\n"
        
        # Link to the description/post
        if link.startswith('http://') or link.startswith('https://'):
            message += f"🔗 <a href='{link}'>View Job</a>\n"
                
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
        logging.error(f"⚠️ Failed to save state file: {e}")

if __name__ == "__main__":
    prevent_sleep()
    start_time = time.time()
    logging.info("Starting job agent run...")
    try:
        main()
    except Exception as e:
        logging.error(f"Job agent failed with error: {e}", exc_info=True)
    finally:
        end_time = time.time()
        elapsed_time = end_time - start_time
        
        # Convert seconds to hours, minutes, seconds for better readability
        hours, rem = divmod(elapsed_time, 3600)
        minutes, seconds = divmod(rem, 60)
        
        time_str = ""
        if hours > 0:
            time_str += f"{int(hours)}h "
        if minutes > 0 or hours > 0:
            time_str += f"{int(minutes)}m "
        time_str += f"{int(seconds)}s"
        
        logging.info(f"Finished job agent run. Total time elapsed: {time_str} ({elapsed_time:.2f} seconds).")
        
        # --- AI Evaluation Step ---
        logging.info("Starting AI evaluation of the run...")
        
        # 1. Get latest CSV
        csv_files = glob.glob("found_jobs_*.csv")
        latest_csv_content = "No jobs found this run."
        if csv_files:
            latest_csv = max(csv_files, key=os.path.getctime)
            try:
                # Read at most the first 50 lines to avoid massive context
                with open(latest_csv, 'r', encoding='utf-8') as f:
                    latest_csv_content = "".join([next(f) for _ in range(51)])
            except StopIteration:
                pass
            except Exception as e:
                latest_csv_content = f"Could not read CSV: {e}"

        # 2. Get logs
        logs_content = "No logs."
        try:
            # Force flush handlers before reading
            for handler in logging.getLogger().handlers:
                handler.flush()
                
            with open("job_agent.log", "r", encoding="utf-8") as f:
                logs_content = f.read()
                # Limit logs size if too big
                if len(logs_content) > 15000:
                    logs_content = "...[TRUNCATED]...\n" + logs_content[-15000:]
        except Exception as e:  
            logs_content = f"Could not read logs: {e}"
            
        try:
            from llm_parser import evaluate_run_with_ai
            from config import USER_BRIEF
            eval_result = evaluate_run_with_ai(logs_content, latest_csv_content, USER_BRIEF)
            
            # 3. Add to brief text file
            with open("evaluation_brief.txt", "w", encoding="utf-8") as f:
                f.write(f"{'='*40}\n")
                f.write(f"Run Evaluation - {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Time Elapsed: {time_str}\n")
                f.write(f"{'='*40}\n")
                f.write(eval_result)
                f.write("\n")
                
            logging.info("AI evaluation saved to evaluation_brief.txt successfully.")
        except Exception as e:
            logging.error(f"Failed to generate or save AI evaluation: {e}")
            
        allow_sleep()