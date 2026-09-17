from core.database import save_job, get_jobs_by_status, get_liked_jobs, cleanup_old_jobs, save_dropped_jobs
from core.scorer import calculate_score, is_valid_job, load_latest_config
from core.job_utils import (
    process_scraped_batch,
    make_job_id as _make_job_id,
    normalize_is_remote as fix_is_remote,
    normalize_job_type as fix_job_type,
    normalize_company as fix_company,
)
from scrapers.glassdoor_scraper import scrape_glassdoor
from scrapers.bayt_scraper import scrape_bayt
from scrapers.tanqeeb_scraper import scrape_tanqeeb
from scrapers.wuzzuf_scraper import scrape_wuzzuf
from scrapers.selenium_scraper import SeleniumSession
from core.config import (
    SITES, RESULTS_PER_TERM, HOURS_OLD, SEARCH_TERMS, LOCATION,
    EXCLUDE_KEYWORDS, EXCLUDED_COMPANIES, FAVORITE_COMPANIES,
    RESUME_KEYWORDS, GLOBAL_REMOTE_KEYWORDS,
    RESTRICTED_REMOTE_KEYWORDS, TARGET_LOCATIONS, TARGET_LEVELS,
    MAX_JOBS_TO_SEND, ROLES
)
import pandas as pd
import sys
import time
import glob
import os
import json
import datetime
import logging
import ctypes
import atexit
import contextlib

# Configure logging to save to file with timestamps, but print to terminal cleanly
# Ensure output directory exists before creating the log file handler
_OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
os.makedirs(_OUTPUT_DIR, exist_ok=True)

CHECKPOINT_FILE = os.path.join(_OUTPUT_DIR, ".scan_checkpoint.json")
PROGRESS_FILE = os.path.join(_OUTPUT_DIR, ".scraper_progress.json")
CHECKPOINT_TTL_HOURS = 24


def format_duration(seconds):
    """Format seconds into a human readable string (e.g. '2m 15s' or '1h 05m')."""
    seconds = int(max(0, seconds))
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}h {m:02d}m {s:02d}s"
    elif m > 0:
        return f"{m}m {s:02d}s"
    else:
        return f"{s}s"


def write_progress(current_step, total_steps, task, jobs_found=0, is_running=True, start_time=None):
    """Atomically writes current scraping progress and estimated remaining time to .scraper_progress.json."""
    try:
        now = time.time()
        elapsed_sec = (now - start_time) if start_time else 0
        
        if total_steps > 0:
            percent = min(100, int((current_step / total_steps) * 100))
        else:
            percent = 0

        if current_step > 0 and start_time and total_steps > current_step:
            avg_sec = elapsed_sec / current_step
            remaining_steps = total_steps - current_step
            eta_sec = remaining_steps * avg_sec
            eta_str = f"~{format_duration(eta_sec)}"
        elif current_step >= total_steps and total_steps > 0:
            eta_sec = 0
            eta_str = "Finishing..."
        else:
            eta_sec = 0
            eta_str = "Calculating..."

        data = {
            "is_running": is_running,
            "percent": percent,
            "current_step": current_step,
            "total_steps": total_steps,
            "task": task,
            "elapsed_seconds": int(elapsed_sec),
            "elapsed_str": format_duration(elapsed_sec),
            "eta_seconds": int(eta_sec),
            "eta_str": eta_str,
            "jobs_found": jobs_found,
            "timestamp": now
        }
        tmp_file = PROGRESS_FILE + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_file, PROGRESS_FILE)
    except Exception as e:
        logging.warning(f"Failed to write scraper progress: {e}")


def cleanup_progress():
    """Marks progress as complete/idle when scraper finishes or exits."""
    try:
        if os.path.exists(PROGRESS_FILE):
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["is_running"] = False
            data["percent"] = 100
            data["task"] = "Completed"
            data["eta_str"] = "Done"
            tmp_file = PROGRESS_FILE + ".tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_file, PROGRESS_FILE)
    except Exception:
        pass


def is_sb_driver_alive(driver):
    """Verifies that the SeleniumBase driver session is active and responsive."""
    if driver is None:
        return False
    try:
        _ = driver.current_url
        return True
    except Exception:
        return False


class ScanCheckpoint:
    def __init__(self, checkpoint_path=CHECKPOINT_FILE):
        self.path = checkpoint_path
        self.completed_tasks = set()
        self.session_id = None
        self.is_resumed = False
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                created_at = data.get('timestamp', 0)
                if (time.time() - created_at) < (CHECKPOINT_TTL_HOURS * 3600):
                    self.completed_tasks = set(data.get('completed_tasks', []))
                    self.session_id = data.get('session_id')
                    self.is_resumed = True
                    logging.info(f"🔄 Resuming previous scan session '{self.session_id}' ({len(self.completed_tasks)} task(s) already completed).")
                else:
                    logging.info(f"🧹 Expired scan checkpoint found (>{CHECKPOINT_TTL_HOURS}h old). Starting a fresh scan session.")
                    self._clear()
            except Exception as e:
                logging.warning(f"⚠️ Failed to read checkpoint file: {e}. Starting fresh.")
                self._clear()

        if not self.session_id:
            self.session_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            self._save()

    def is_completed(self, task_key: str) -> bool:
        return task_key in self.completed_tasks

    def mark_completed(self, task_key: str):
        self.completed_tasks.add(task_key)
        self._save()

    def _save(self):
        try:
            data = {
                'session_id': self.session_id,
                'timestamp': time.time(),
                'completed_tasks': list(self.completed_tasks)
            }
            tmp_path = self.path + ".tmp"
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, self.path)
        except Exception as e:
            logging.warning(f"⚠️ Failed to save scan checkpoint: {e}")

    def clear(self):
        self._clear()

    def _clear(self):
        self.completed_tasks = set()
        self.session_id = None
        self.is_resumed = False
        if os.path.exists(self.path):
            try:
                os.remove(self.path)
            except OSError:
                pass

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


def ensure_network_connection(timeout=60):
    """Waits for internet network connection to become active (DNS + socket check).
    Crucial for Windows Task Scheduler scheduled runs waking from sleep."""
    import socket
    start_t = time.time()
    hosts_to_check = [("8.8.8.8", 53), ("1.1.1.1", 53), ("www.google.com", 80)]
    logging.info("Checking internet connectivity before starting scraping...")

    while time.time() - start_t < timeout:
        for host, port in hosts_to_check:
            try:
                with socket.create_connection((host, port), timeout=3):
                    logging.info(f"✓ Network connection confirmed via {host}:{port}.")
                    return True
            except OSError:
                pass
        time.sleep(3)

    logging.warning(f"⚠️ Network check timed out after {timeout}s. Scraper will proceed anyway...")
    return False


class ConsoleFilter(logging.Filter):
    """Filters out overly verbose 3rd-party logs from the console."""
    def filter(self, record):
        noisy_prefixes = ("urllib3", "selenium", "seleniumbase", "playwright", "asyncio", "httpcore", "httpx")
        return not any(record.name.startswith(p) for p in noisy_prefixes)


def setup_logging(is_resumed: bool = False):
    """Configures root logging with INFO level.

    Clears the log file for new runs (mode='w'), appends for resumed sessions (mode='a').
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    for h in list(root_logger.handlers):
        root_logger.removeHandler(h)

    log_file = os.path.join(_OUTPUT_DIR, "job_agent.log")
    file_mode = "a" if is_resumed else "w"

    file_handler = logging.FileHandler(log_file, mode=file_mode, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s'))
    root_logger.addHandler(file_handler)

    if sys.stdout is not None:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(logging.Formatter('%(message)s'))
        console_handler.addFilter(ConsoleFilter())
        root_logger.addHandler(console_handler)

    return file_handler


# Default logger initialization on import (append mode so importing doesn't overwrite logs)
setup_logging(is_resumed=True)


try:
    from scrapers.playwright_scraper import get_posts_as_dataframe, scrape_linkedin_jobs_playwright, LinkedInSession
except ImportError:
    get_posts_as_dataframe = None
    scrape_linkedin_jobs_playwright = None
    LinkedInSession = None


if sys.stdout is not None and getattr(sys.stdout, 'encoding', None) and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass


def main(run_start_time=None, reload_cfg=False):

    import concurrent.futures
    import re
    from datetime import date
    from tqdm import tqdm
    if reload_cfg:
        import core.config as cfg
        cfg.reload_config()

    jobs_list = []
    sites_lower = {s.lower() for s in SITES}  # Pre-computed set for O(1) lookups

    run_start_time = run_start_time or time.time()
    checkpoint = ScanCheckpoint()
    setup_logging(is_resumed=checkpoint.is_resumed)
    if checkpoint.is_resumed:
        logging.info(f"=== Resuming Scan Session '{checkpoint.session_id}' ({len(checkpoint.completed_tasks)} tasks completed) ===")
    else:
        logging.info(f"=== Starting New Scan Session '{checkpoint.session_id}' ===")

    http_sites = {'tanqeeb', 'bayt'} & sites_lower
    li_sites = {'linkedin', 'linkedin_posts'} & sites_lower
    sb_sites = {'wuzzuf', 'glassdoor', 'indeed'} & sites_lower

    total_searches = len(SEARCH_TERMS) * len(LOCATION)
    active_phases_count = sum([bool(http_sites), bool(li_sites), bool(sb_sites)])
    total_steps = total_searches * max(1, active_phases_count)
    current_step = [0]
    total_jobs_saved = [0]

    write_progress(0, total_steps, "Initializing job search...", 0, is_running=True, start_time=run_start_time)

    def save_jobs_to_db(df_list):
        """Clean, normalize, score, and incrementally save scraped jobs to SQLite using core.job_utils."""
        return process_scraped_batch(df_list)

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

    # -------------------------------------------------------------------------
    # PHASE 1: Fast HTTP Scrapers (Tanqeeb, Bayt)
    # Pure HTTP, zero browser overhead, runs concurrently via ThreadPool
    # -------------------------------------------------------------------------
    if http_sites:
        logging.info("🚀 [Phase 1/3] Starting Fast HTTP Scrapers (Tanqeeb, Bayt)...")
        with tqdm(total=total_searches, desc="[HTTP Scrapers]", unit="search") as pbar:
            for term in SEARCH_TERMS:
                for loc in LOCATION:
                    current_step[0] += 1
                    task_label = f"[HTTP] '{term}' in '{loc}'"
                    write_progress(current_step[0], total_steps, task_label, total_jobs_saved[0], is_running=True, start_time=run_start_time)
                    task_key = f"http:{term}|{loc}"
                    if checkpoint.is_completed(task_key):
                        logging.info(f"⏭️ Skipping completed search {task_key} (restored from checkpoint)")
                        pbar.update(1)
                        continue

                    phase_results = []
                    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                        futures = []
                        if 'tanqeeb' in sites_lower:
                            futures.append(executor.submit(retry_scraper, scrape_tanqeeb, term, loc, RESULTS_PER_TERM, HOURS_OLD))
                        if 'bayt' in sites_lower:
                            futures.append(executor.submit(retry_scraper, scrape_bayt, term, loc, RESULTS_PER_TERM, HOURS_OLD))

                        for future in concurrent.futures.as_completed(futures):
                            try:
                                res = future.result(timeout=60)
                                if res is not None and not res.empty:
                                    phase_results.append(res)
                            except concurrent.futures.TimeoutError:
                                logging.warning(f"⚠️ HTTP scraper timed out after 60s for '{term}' in '{loc}'.")
                            except Exception as e:
                                logging.error(f"⚠️ HTTP scraper failure for '{term}' in '{loc}': {e}")

                    if phase_results:
                        saved_df = save_jobs_to_db(phase_results)
                        if saved_df is not None and not saved_df.empty:
                            jobs_list.append(saved_df)
                            total_jobs_saved[0] += len(saved_df)
                            write_progress(current_step[0], total_steps, f"Found {len(saved_df)} jobs for '{term}' in '{loc}'", total_jobs_saved[0], is_running=True, start_time=run_start_time)

                    checkpoint.mark_completed(task_key)
                    pbar.update(1)

    # -------------------------------------------------------------------------
    # PHASE 2: LinkedIn Scrapers (Playwright / Guest API)
    # Browser session is isolated exclusively to LinkedIn, then cleanly closed
    # -------------------------------------------------------------------------
    if li_sites:
        logging.info("🚀 [Phase 2/3] Starting LinkedIn Scrapers (Playwright / Guest API)...")

        def _run_linkedin_term_loc(term, loc, li_page=None):
            search_loc = "worldwide" if loc.lower() == "remote" else loc
            res_list = []
            if 'linkedin' in sites_lower:
                if li_page is not None and scrape_linkedin_jobs_playwright:
                    res = retry_scraper(scrape_linkedin_jobs_playwright, term, search_loc, RESULTS_PER_TERM, HOURS_OLD, li_page)
                    if res is not None and not res.empty:
                        res_list.append(res)
                else:
                    try:
                        from scrapers.playwright_scraper import scrape_linkedin_guest_api
                        res = retry_scraper(scrape_linkedin_guest_api, term, search_loc, RESULTS_PER_TERM, HOURS_OLD)
                        if res is not None and not res.empty:
                            res_list.append(res)
                    except Exception as e:
                        logging.error(f"⚠️ LinkedIn guest API failed for '{term}' in '{loc}': {e}")

            if 'linkedin_posts' in sites_lower and get_posts_as_dataframe and li_page is not None:
                res = retry_scraper(get_posts_as_dataframe, term, loc, li_page)
                if res is not None and not res.empty:
                    res_list.append(res)

            return res_list

        with tqdm(total=total_searches, desc="[LinkedIn]", unit="search") as pbar:
            if LinkedInSession:
                try:
                    with LinkedInSession() as li_page:
                        for term in SEARCH_TERMS:
                            for loc in LOCATION:
                                current_step[0] += 1
                                task_label = f"[LinkedIn] '{term}' in '{loc}'"
                                write_progress(current_step[0], total_steps, task_label, total_jobs_saved[0], is_running=True, start_time=run_start_time)
                                task_key = f"linkedin:{term}|{loc}"
                                if checkpoint.is_completed(task_key):
                                    logging.info(f"⏭️ Skipping completed search {task_key} (restored from checkpoint)")
                                    pbar.update(1)
                                    continue

                                res_list = _run_linkedin_term_loc(term, loc, li_page)
                                if res_list:
                                    saved_df = save_jobs_to_db(res_list)
                                    if saved_df is not None and not saved_df.empty:
                                        jobs_list.append(saved_df)
                                        total_jobs_saved[0] += len(saved_df)
                                        write_progress(current_step[0], total_steps, f"Found {len(saved_df)} jobs for '{term}' in '{loc}'", total_jobs_saved[0], is_running=True, start_time=run_start_time)

                                checkpoint.mark_completed(task_key)
                                pbar.update(1)
                except Exception as e:
                    logging.warning(f"⚠️ LinkedIn browser session error: {e}. Falling back to guest API for remaining searches.")
                    for term in SEARCH_TERMS:
                        for loc in LOCATION:
                            task_key = f"linkedin:{term}|{loc}"
                            if not checkpoint.is_completed(task_key):
                                res_list = _run_linkedin_term_loc(term, loc, li_page=None)
                                if res_list:
                                    saved_df = save_jobs_to_db(res_list)
                                    if saved_df is not None and not saved_df.empty:
                                        jobs_list.append(saved_df)
                                        total_jobs_saved[0] += len(saved_df)
                                checkpoint.mark_completed(task_key)
            else:
                # No Playwright available, use guest API directly
                for term in SEARCH_TERMS:
                    for loc in LOCATION:
                        current_step[0] += 1
                        task_label = f"[LinkedIn Guest] '{term}' in '{loc}'"
                        write_progress(current_step[0], total_steps, task_label, total_jobs_saved[0], is_running=True, start_time=run_start_time)
                        task_key = f"linkedin:{term}|{loc}"
                        if checkpoint.is_completed(task_key):
                            pbar.update(1)
                            continue

                        res_list = _run_linkedin_term_loc(term, loc, li_page=None)
                        if res_list:
                            saved_df = save_jobs_to_db(res_list)
                            if saved_df is not None and not saved_df.empty:
                                jobs_list.append(saved_df)
                                total_jobs_saved[0] += len(saved_df)

                        checkpoint.mark_completed(task_key)
                        pbar.update(1)

    # -------------------------------------------------------------------------
    # PHASE 3: Regional Browser Scrapers (SeleniumBase - Wuzzuf, Glassdoor, Indeed)
    # Browser session is isolated exclusively to SeleniumBase, then cleanly closed
    # -------------------------------------------------------------------------
    if sb_sites:
        logging.info("🚀 [Phase 3/3] Starting Browser Scrapers (Wuzzuf, Glassdoor, Indeed)...")
        with tqdm(total=total_searches, desc="[Browser Scrapers]", unit="search") as pbar:
            try:
                from scrapers.selenium_scraper import SeleniumSession
            except ImportError:
                SeleniumSession = None

            sb_ctx = SeleniumSession() if SeleniumSession else contextlib.nullcontext(None)
            with sb_ctx as sb_driver:
                if is_sb_driver_alive(sb_driver):
                    for term in SEARCH_TERMS:
                        for loc in LOCATION:
                            current_step[0] += 1
                            task_label = f"[Browser] '{term}' in '{loc}'"
                            write_progress(current_step[0], total_steps, task_label, total_jobs_saved[0], is_running=True, start_time=run_start_time)
                            task_key = f"selenium:{term}|{loc}"
                            if checkpoint.is_completed(task_key):
                                logging.info(f"⏭️ Skipping completed search {task_key} (restored from checkpoint)")
                                pbar.update(1)
                                continue

                            phase_results = []
                            # Wuzzuf
                            if 'wuzzuf' in sites_lower:
                                try:
                                    res = retry_scraper(scrape_wuzzuf, term, loc, RESULTS_PER_TERM, HOURS_OLD, sb_driver)
                                    if res is not None and not res.empty:
                                        phase_results.append(res)
                                except Exception as e:
                                    logging.error(f"⚠️ Wuzzuf scraper failed for '{term}' in '{loc}': {e}")

                            # Glassdoor
                            if 'glassdoor' in sites_lower:
                                try:
                                    res = retry_scraper(scrape_glassdoor, term, loc, RESULTS_PER_TERM, HOURS_OLD, sb_driver)
                                    if res is not None and not res.empty:
                                        phase_results.append(res)
                                except Exception as e:
                                    logging.error(f"⚠️ Glassdoor scraper failed for '{term}' in '{loc}': {e}")

                            # Indeed
                            if 'indeed' in sites_lower:
                                try:
                                    from scrapers.indeed_scraper import scrape_indeed
                                    res = retry_scraper(scrape_indeed, term, loc, RESULTS_PER_TERM, HOURS_OLD, sb_driver)
                                    if res is not None and not res.empty:
                                        phase_results.append(res)
                                except ImportError:
                                    pass
                                except Exception as e:
                                    logging.error(f"⚠️ Indeed scraper failed for '{term}' in '{loc}': {e}")

                            if phase_results:
                                saved_df = save_jobs_to_db(phase_results)
                                if saved_df is not None and not saved_df.empty:
                                    jobs_list.append(saved_df)
                                    total_jobs_saved[0] += len(saved_df)
                                    write_progress(current_step[0], total_steps, f"Found {len(saved_df)} jobs for '{term}' in '{loc}'", total_jobs_saved[0], is_running=True, start_time=run_start_time)

                            checkpoint.mark_completed(task_key)
                            pbar.update(1)
                else:
                    logging.warning("⚠️ SeleniumBase browser is disconnected/closed. Skipping browser-based scrapers.")
                    for term in SEARCH_TERMS:
                        for loc in LOCATION:
                            current_step[0] += 1
                            pbar.update(1)

    # Clear checkpoint file now that full run finished cleanly
    checkpoint.clear()
    write_progress(total_steps, total_steps, "Search complete. Saving results...", total_jobs_saved[0], is_running=True, start_time=run_start_time)

    if jobs_list:
        cleaned_jobs_list = [df.dropna(axis=1, how='all') for df in jobs_list if df is not None and not df.empty]
        if cleaned_jobs_list:
            all_jobs = pd.concat(cleaned_jobs_list, ignore_index=True)
            all_jobs = all_jobs.drop_duplicates(subset=["job_url"])
            if not all_jobs.empty:
                sort_cols = ['relevance_score']
                ascending_flags = [False]
                if 'date_posted' in all_jobs.columns:
                    sort_cols.append('date_posted')
                    ascending_flags.append(False)

                all_jobs = all_jobs.sort_values(by=sort_cols, ascending=ascending_flags)
                best_100 = all_jobs.head(100).copy()
                if 'description' in best_100.columns:
                    best_100 = best_100.drop(columns=['description'])

                current_date_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                filename = os.path.join(_OUTPUT_DIR, f"found_jobs_{current_date_str}.csv")
                best_100.to_csv(filename, index=False)

    thirty_days_ago = time.time() - (30 * 24 * 60 * 60)
    for f in glob.glob(os.path.join(_OUTPUT_DIR, "found_jobs_*.csv")):
        try:
            if os.path.getmtime(f) < thirty_days_ago:
                os.remove(f)
        except Exception as e:
            logging.warning(f"⚠️ Failed to delete old job file {f}: {e}")

    try:
        with open(os.path.join(os.path.dirname(__file__), 'core', 'config.json'), 'r', encoding='utf-8') as f:
            c_data = json.load(f)
            retention_days = c_data.get('job_retention_days', 90)
        deleted = cleanup_old_jobs(days=retention_days)
        logging.info(f"🧹 Cleaned up {deleted} jobs older than {retention_days} days from the database.")
        from core.scorer import rescore_all_jobs
        rescore_all_jobs()
    except Exception as e:
        logging.error(f"⚠️ Failed to clean up or rescore old jobs from database: {e}")

    logging.info(f"=== Run Summary: Saved {total_jobs_saved[0]} new job(s) to SQLite. Generated {len(jobs_list)} batch(es). ===")


def cleanup_lock():
    cleanup_progress()
    lock_path = os.path.join(_OUTPUT_DIR, ".scraper.lock")
    try:
        if os.path.exists(lock_path):
            with open(lock_path, "r", encoding="utf-8") as lf:
                pid = int(lf.read().strip())
            if pid == os.getpid():
                os.remove(lock_path)
    except Exception:
        try:
            if os.path.exists(lock_path):
                os.remove(lock_path)
        except OSError:
            pass


if __name__ == "__main__":
    prevent_sleep()
    ensure_network_connection(timeout=60)
    
    lock_path = os.path.join(_OUTPUT_DIR, ".scraper.lock")
    if os.path.exists(lock_path):
        try:
            with open(lock_path, "r", encoding="utf-8") as lf:
                old_pid = int(lf.read().strip())
            from web.app import is_process_running
            if old_pid and is_process_running(old_pid) and old_pid != os.getpid():
                logging.error(f"❌ Scraper is already running under PID {old_pid}. Exiting.")
                sys.exit(0)
            else:
                logging.warning(f"⚠️ Found stale lock file from crashed process (PID {old_pid}). Cleaning up.")
                os.remove(lock_path)
        except Exception:
            pass

    try:
        with open(lock_path, "w", encoding="utf-8") as lf:
            lf.write(str(os.getpid()))
    except Exception as e:
        logging.warning(f"Could not create lock file: {e}")

    atexit.register(cleanup_lock)

    start_time = time.time()
    logging.info("Starting job agent run...")
    try:
        main(run_start_time=start_time, reload_cfg=True)
    except Exception as e:
        logging.error(f"Job agent failed with error: {e}", exc_info=True)
    finally:
        end_time = time.time()
        elapsed_time = end_time - start_time

        hours, rem = divmod(elapsed_time, 3600)
        minutes, seconds = divmod(rem, 60)

        time_str = ""
        if hours > 0:
            time_str += f"{int(hours)}h "
        if minutes > 0 or hours > 0:
            time_str += f"{int(minutes)}m "
        time_str += f"{int(seconds)}s"

        logging.info(f"Finished job agent run. Total time elapsed: {time_str} ({elapsed_time:.2f} seconds).")

        logging.info("Starting AI evaluation of the run...")

        csv_files = glob.glob(os.path.join(_OUTPUT_DIR, "found_jobs_*.csv"))
        latest_csv_content = "No jobs found this run."
        if csv_files:
            latest_csv = max(csv_files, key=os.path.getmtime)
            try:
                with open(latest_csv, 'r', encoding='utf-8') as f:
                    latest_csv_content = "".join([next(f) for _ in range(51)])
            except StopIteration:
                pass
            except Exception as e:
                latest_csv_content = f"Could not read CSV: {e}"

        logs_content = "No logs."
        try:
            for handler in logging.getLogger().handlers:
                handler.flush()

            with open(os.path.join(_OUTPUT_DIR, "job_agent.log"), "r", encoding="utf-8") as f:
                logs_content = f.read()
                if len(logs_content) > 15000:
                    logs_content = "...[TRUNCATED]...\n" + logs_content[-15000:]
        except Exception as e:
            logs_content = f"Could not read logs: {e}"

        try:
            from core.llm_parser import evaluate_run_with_ai
            from core.config import USER_BRIEF
            eval_result = evaluate_run_with_ai(logs_content, latest_csv_content, USER_BRIEF)

            with open(os.path.join(_OUTPUT_DIR, "evaluation_brief.txt"), "w", encoding="utf-8") as f:
                f.write(f"{'='*40}\n")
                f.write(f"Run Evaluation - {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Time Elapsed: {time_str}\n")
                f.write(f"{'='*40}\n")
                f.write(eval_result)
                f.write("\n")

            logging.info("AI evaluation saved to evaluation_brief.txt successfully.")
            
            from core.config_tuner import analyze_run_and_tune_config
            analyze_run_and_tune_config(logs_content, eval_result)
            
        except Exception as e:
            logging.error(f"Failed to generate or save AI evaluation: {e}")

        cleanup_lock()
        allow_sleep()
