import os
import time
import json
import re
import urllib.parse
import random
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
import sys
import logging
from llm_parser import extract_post_with_ai, extract_job_page_with_ai, extract_feed_posts_with_ai

LOGIN_FAILED = False

if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(BASE_DIR, '.env')
USER_DATA_DIR = os.path.join(BASE_DIR, "playwright_profile")
load_dotenv(dotenv_path=env_path)

def auto_login_if_needed(page):
    global LOGIN_FAILED
    if LOGIN_FAILED:
        logging.warning("⚠️ Skipping auto-login attempt because a previous attempt failed in this session.")
        return

    email = os.getenv("LINKEDIN_EMAIL")
    password = os.getenv("LINKEDIN_PASSWORD")
    
    # Check if we are on a login page or authwall, or if login fields exist
    if "login" in page.url or "authwall" in page.url or page.query_selector('input[id="username"]') or page.query_selector('input[id="session_key"]'):
        if email and password:
            logging.info("🔐 Playwright is logged out. Attempting auto-login...")
            try:
                page.goto("https://www.linkedin.com/login")
                page.wait_for_load_state("domcontentloaded")
                time.sleep(random.uniform(2, 4))
                
                if page.query_selector('input[id="username"]'):
                    page.fill('input[id="username"]', email)
                    page.fill('input[id="password"]', password)
                    page.click('button[type="submit"]')
                elif page.query_selector('input[id="session_key"]'):
                    page.fill('input[id="session_key"]', email)
                    page.fill('input[id="session_password"]', password)
                    try:
                        page.click('button[data-id="sign-in-form__submit-btn"]', timeout=3000)
                    except:
                        page.click('button[type="submit"]', timeout=3000)
                    
                try:
                    page.wait_for_url(lambda url: "login" not in url and "checkpoint" not in url and "challenge" not in url, timeout=10000)
                except:
                    pass
                time.sleep(random.uniform(3, 5))
                
                if "challenge" in page.url or "checkpoint" in page.url:
                    logging.warning("⚠️ LinkedIn is asking for a security check. Please run linkedin_login.py manually.")
                    LOGIN_FAILED = True
                elif "login" in page.url or "authwall" in page.url:
                    logging.error("❌ Auto-login failed (possibly due to headless mode). Please run linkedin_login.py manually.")
                    LOGIN_FAILED = True
                else:
                    logging.info("✅ Auto-login submitted and seems successful!")
            except Exception as e:
                logging.error(f"⚠️ Auto-login error: {e}")
                LOGIN_FAILED = True
        else:
            logging.error("❌ Playwright is logged out but LINKEDIN_EMAIL/LINKEDIN_PASSWORD not in .env")



def scrape_linkedin_posts_playwright(keyword):
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=True
        )
        context.grant_permissions(['clipboard-read', 'clipboard-write'])

        page = context.pages[0] if context.pages else context.new_page()
        Stealth().apply_stealth_sync(page)
        
        try:
            # First, check if we're logged in by visiting the feed
            page.goto('https://www.linkedin.com/feed/', wait_until='domcontentloaded')
            auto_login_if_needed(page)

            # Now perform the search
            encoded_keyword = urllib.parse.quote(keyword)
            # origin=GLOBAL_SEARCH_HEADER ensures we get normal content search results
            search_url = f"https://www.linkedin.com/search/results/content/?keywords={encoded_keyword}&origin=GLOBAL_SEARCH_HEADER&sortBy=%22date_posted%22"
            
            page.goto(search_url, wait_until='domcontentloaded')
            
            # Scroll down to load more posts
            for i in range(3):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(4)
                
            # Extract all visible text from the page, separating posts and adding URLs
            page_text = page.evaluate('''() => {
                let result = "";
                
                let isAuthorLink = (href) => href && (href.includes('/in/') || href.includes('/company/'));
                let allAnchors = Array.from(document.querySelectorAll('a'));

                // Find posts by locating their Control Menu buttons, which are very reliable
                let menuBtns = document.querySelectorAll('button[aria-label*="Control Menu"], button[aria-label*="control menu" i], .feed-shared-control-menu__trigger, .artdeco-dropdown__trigger');
                
                let posts = Array.from(menuBtns).map(btn => {
                    return btn.closest('li.reusable-search__result-container') || btn.closest('.feed-shared-update-v2') || btn.closest('.search-entity') || btn.closest('li') || btn.parentElement?.parentElement?.parentElement;
                }).filter(Boolean);
                
                posts = Array.from(new Set(posts)); // Remove duplicates

                if (posts.length === 0) {
                    return document.body.innerText;
                }

                for (let post of posts) {
                    let url = "";
                    
                    // Since URNs are completely stripped from the new search DOM and clipboard is blocked in headless mode,
                    // the most reliable fallback is to extract the Author's Profile URL so the user can find the post in their Recent Activity.
                    let links = post.querySelectorAll('a');
                    for (let a of links) {
                        if (isAuthorLink(a.href)) {
                            url = a.href.split('?')[0];
                            break; // First profile link is usually the author
                        }
                    }
                    
                    let text = post.innerText;
                    if (text && text.trim().length > 20) {
                        if (url) {
                            result += "Author/Company URL: " + url + "\\n";
                            result += "(Note: Direct post link unavailable in headless mode. Visit author's Recent Activity to view post.)\\n";
                        }
                        result += "Post Text:\\n" + text + "\\n\\n---END OF POST---\\n\\n";
                    }
                }
                
                return result || document.body.innerText;
            }''')
            return page_text
                    
        except Exception as e:
            logging.error(f"⚠️ Error during Playwright execution: {e}")
        finally:
            context.close()
        
    return ""

def scrape_linkedin_jobs_playwright(term, location, results_wanted=5, hours_old=None):
    """Scrapes regular LinkedIn Jobs using the authenticated Playwright session."""
    import urllib.parse
    import datetime
    import random
    import pandas as pd
    
    jobs = []
    
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=True
        )
        page = context.pages[0] if context.pages else context.new_page()
        Stealth().apply_stealth_sync(page)
        
        # Build search URL
        encoded_term = urllib.parse.quote(term)
        encoded_loc = urllib.parse.quote(location)
        
        url = f"https://www.linkedin.com/jobs/search/?keywords={encoded_term}&location={encoded_loc}"
        if hours_old:
            seconds_old = hours_old * 3600
            url += f"&f_TPR=r{seconds_old}"
            
        logging.info(f"🔍 Searching LinkedIn Jobs (Playwright): {term} in {location}")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=40000)
            time.sleep(random.uniform(3, 5))
            
            auto_login_if_needed(page)
            
            if "login" in page.url or "authwall" in page.url:
                page.goto(url, wait_until="domcontentloaded", timeout=40000)
                time.sleep(random.uniform(3, 5))
            
            # Scroll a bit to load job list
            for _ in range(3):
                page.mouse.wheel(0, 1000)
                time.sleep(1)
                
            # Extract job links
            links = page.evaluate('''() => {
                const anchors = Array.from(document.querySelectorAll('a'));
                const jobLinks = new Set();
                anchors.forEach(a => {
                    if (a.href && (a.href.includes('/jobs/view/') || a.href.includes('currentJobId='))) {
                        let cleanUrl = a.href.split('?')[0];
                        if (a.href.includes('currentJobId=')) {
                            const params = new URLSearchParams(a.search);
                            if (params.get('currentJobId')) {
                                cleanUrl = 'https://www.linkedin.com/jobs/view/' + params.get('currentJobId');
                            }
                        }
                        jobLinks.add(cleanUrl);
                    }
                });
                return Array.from(jobLinks);
            }''')
            
            # Limit to results_wanted
            links = links[:results_wanted]
            
            for job_url in links:
                try:
                    # Retry loop to handle LinkedIn connection drops or timeouts
                    for attempt in range(2):
                        try:
                            page.goto(job_url, wait_until="domcontentloaded", timeout=25000)
                            time.sleep(random.uniform(2, 4))
                            break
                        except Exception as page_e:
                            if attempt == 0:
                                logging.warning(f"    (Retrying job load: {str(page_e).splitlines()[0][:50]}...)")
                                time.sleep(random.uniform(4, 7))
                            else:
                                raise page_e
                    
                    # Try clicking "See more" if needed
                    see_more_btn = page.query_selector('.jobs-description__footer-button') or \
                                   page.query_selector('button[aria-label="Click to see more description"]')
                    if see_more_btn:
                        try:
                            see_more_btn.click(timeout=3000)
                            time.sleep(1)
                        except:
                            pass
                            
                    # Fetch all visible text on the page for AI extraction
                    page_text = page.evaluate("document.body.innerText")
                    ai_data = extract_job_page_with_ai(page_text[:10000]) # Pass first 10k chars to avoid token limits
                    
                    if ai_data and not ai_data.get("error"):
                        title = ai_data.get('title', 'Unknown')
                        if title != "Unknown" and title != "Not specified":
                            jobs.append({
                                'title': title,
                                'company': ai_data.get('company', 'Unknown'),
                                'location': ai_data.get('location', location),
                                'job_url': job_url,
                                'description': ai_data.get('description', ''),
                                'site': 'linkedin',
                                'is_remote': 'remote' in str(ai_data.get('location', '')).lower() or 'remote' in location.lower(),
                                'date_posted': ai_data.get('date_posted') or datetime.date.today(),
                                'job_type': 'Not specified'
                            })
                    else:
                        logging.warning(f"⚠️ AI Parsing failed for job {job_url}: {ai_data.get('error') if ai_data else 'Unknown'}")
                    
                except Exception as e:
                    logging.error(f"⚠️ Failed to parse job {job_url}: {e}")
                    
        except Exception as e:
            logging.error(f"⚠️ LinkedIn Search failed for {term}: {e}")
            
        context.close()
        
    return pd.DataFrame(jobs)

def get_posts_as_dataframe(term, loc):
    """Integrates with job_agent.py by returning a pandas DataFrame."""
    import pandas as pd
    from datetime import date
    
    keyword = f"hiring {term} {loc}"
    feed_text = scrape_linkedin_posts_playwright(keyword)
    
    if not feed_text or len(feed_text) < 50:
        return pd.DataFrame()
        
    valid_jobs = []
    
    ai_data = extract_feed_posts_with_ai(feed_text[:15000]) # Pass up to 15k chars
    
    if ai_data and not ai_data.get("error"):
        jobs_list = ai_data.get("jobs", [])
        for job in jobs_list:
            if job.get("is_job"):
                valid_jobs.append({
                    'title': job.get('title', 'Unknown'),
                    'company': job.get('company', 'Unknown'),
                    'location': job.get('location', loc),
                    'job_url': job.get('job_url') or f"https://www.linkedin.com/search/results/content/?keywords={keyword}", 
                    'description': job.get('description', ''),
                    'is_remote': 'remote' in str(job.get('location', '')).lower(),
                    'date_posted': job.get('date_posted') or date.today(),
                    'job_type': 'Not specified',
                    'site': 'linkedin_posts'
                })
    else:
        logging.warning(f"⚠️ Error from Gemini: {ai_data.get('error') if ai_data else 'Unknown'}")
            
    if valid_jobs:
        return pd.DataFrame(valid_jobs)
    return pd.DataFrame()

if __name__ == "__main__":
    print("--- Playwright LinkedIn Post Scraper ---")
    if not os.getenv("GEMINI_API_KEY"):
        print("⚠️ Warning: GEMINI_API_KEY not found in .env. AI Extraction will be disabled.\n")
        
    feed_text = scrape_linkedin_posts_playwright("hiring data scientist egypt")
    
    if feed_text:
        print(f"\n--- Processing Feed with Gemini AI ---")
        print(f"Extracted {len(feed_text)} characters of feed text.")
        
        print("🧠 AI Extraction:")
        ai_data = extract_feed_posts_with_ai(feed_text[:15000])
        print(json.dumps(ai_data, indent=2, ensure_ascii=False))
        print("-" * 50)
    else:
        print("\nNo posts were found. Check your cookie or search terms.")
