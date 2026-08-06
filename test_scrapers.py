import os
import sys
import logging

# Ensure the root directory is in sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from scrapers.wuzzuf_scraper import scrape_wuzzuf
from scrapers.tanqeeb_scraper import scrape_tanqeeb
from scrapers.bayt_scraper import scrape_bayt
from scrapers.glassdoor_scraper import scrape_glassdoor
try:
    from scrapers.indeed_scraper import scrape_indeed
except ImportError as e:
    logging.warning(f"indeed_scraper unavailable: {e}")
    scrape_indeed = None

try:
    from scrapers.playwright_scraper import scrape_linkedin_jobs_playwright, LinkedInSession
except ImportError as e:
    logging.warning(f"playwright_scraper unavailable: {e}")
    scrape_linkedin_jobs_playwright = None
    LinkedInSession = None


def test_scraper(name, func, *args):
    print(f"\n--- Testing {name} ---")
    try:
        df = func(*args)
        if df is not None and not df.empty:
            print(f"Success! Scraped {len(df)} jobs.")
            print("First job:")
            print(df.iloc[0].to_dict())
        else:
            print("No jobs found or returned empty DataFrame.")
    except Exception as e:
        print(f"Error testing {name}: {e}")

if __name__ == "__main__":
    term = "Software Engineer"
    loc = "Egypt"
    results = 1
    hours = None  # None means bypass the time filter to ensure we scrape at least 1 job for testing

    try:
        from scrapers.selenium_scraper import SeleniumSession
    except ImportError:
        SeleniumSession = None

    if LinkedInSession and scrape_linkedin_jobs_playwright and SeleniumSession:
        print("\n--- Testing with Playwright & SeleniumBase ---")
        try:
            with SeleniumSession() as sb_driver:
                test_scraper("Wuzzuf", scrape_wuzzuf, term, loc, results, hours, sb_driver)
                test_scraper("Tanqeeb", scrape_tanqeeb, term, loc, results, hours)
                test_scraper("Bayt", scrape_bayt, term, loc, results, hours, sb_driver)
                test_scraper("Glassdoor", scrape_glassdoor, term, loc, results, hours, sb_driver)
                if scrape_indeed:
                    test_scraper("Indeed", scrape_indeed, term, loc, results, hours, sb_driver)
                    
            with LinkedInSession() as page:
                print("\n--- Testing LinkedIn (Playwright) ---")
                df = scrape_linkedin_jobs_playwright(term, loc, results, hours, page)
                if df is not None and not df.empty:
                    print(f"Success! Scraped {len(df)} jobs.")
                    print("First job:")
                    print(df.iloc[0].to_dict())
                else:
                    print("No jobs found or returned empty DataFrame.")
        except Exception as e:
            print(f"Error testing session: {e}")
    else:
        print("\n--- Playwright/Selenium session not available ---")
