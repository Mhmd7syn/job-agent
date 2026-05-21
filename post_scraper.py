import os
import json
import time
import random
from dotenv import load_dotenv

# --- Monkey-patch BeautifulSoup to bypass lxml requirement on Python 3.14 ---
import bs4
original_bs = bs4.BeautifulSoup
def patched_bs(*args, **kwargs):
    if 'features' in kwargs and kwargs['features'] == 'lxml':
        kwargs['features'] = 'html.parser'
    elif len(args) > 1 and args[1] == 'lxml':
        args = (args[0], 'html.parser') + args[2:]
    return original_bs(*args, **kwargs)
bs4.BeautifulSoup = patched_bs
# -------------------------------------------------------------------------

from linkedin_api import Linkedin
import sys

if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# Load environment variables
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(BASE_DIR, '.env')
load_dotenv(dotenv_path=env_path)

LINKEDIN_LI_AT = os.getenv("LINKEDIN_LI_AT")
LINKEDIN_JSESSIONID = os.getenv("LINKEDIN_JSESSIONID")

def scrape_linkedin_posts(keyword):
    """
    Connects to LinkedIn using the unofficial API to search for posts.
    Ensure you use a dummy account, as this has a high risk of getting banned.
    """
    if not LINKEDIN_LI_AT or not LINKEDIN_JSESSIONID:
        print("❌ Error: Please add LINKEDIN_LI_AT and LINKEDIN_JSESSIONID to your .env file.")
        return []

    print(f"🔐 Authenticating with LinkedIn using session cookies...")
    try:
        import requests
        # Authenticate using cookies to bypass the login block
        custom_cookies = requests.utils.cookiejar_from_dict({
            "li_at": LINKEDIN_LI_AT,
            "JSESSIONID": LINKEDIN_JSESSIONID
        })
        api = Linkedin('dummy_user', 'dummy_pass', cookies=custom_cookies)
    except Exception as e:
        print(f"❌ Authentication failed! Check credentials or 2FA requirements. Error: {e}")
        return []

    print(f"🔍 Searching LinkedIn posts for: '{keyword}'...")
    found_posts = []
    
    try:
        # Search for posts matching the keyword
        # Note: The search endpoint parameters can sometimes change if LinkedIn updates their API.
        # We use a general keyword search focused on posts.
        results = api.search(
            {"keywords": keyword},
            limit=20 # Be careful not to set this too high to avoid immediate bans
        )
        
        # Parse the results
        if results:
            for item in results:
                # The exact JSON structure returned by the unofficial API varies.
                # Usually, 'urn:li:activity' or text fields are present.
                # We extract the raw text snippet and a link if possible.
                post_text = str(item.get("summary", item.get("title", item)))
                
                # Basic filter to ensure it's not just an empty object
                if len(post_text) > 10:
                    found_posts.append({
                        "text": post_text,
                        "raw_data": item
                    })
                    
        print(f"✅ Found {len(found_posts)} posts for '{keyword}'")
        
    except Exception as e:
        print(f"⚠️ Error while searching posts: {e}")

    # Always sleep to mimic human behavior
    time.sleep(random.uniform(5, 10))
    
    return found_posts

if __name__ == "__main__":
    print("--- LinkedIn Post Scraper Test ---")
    print("WARNING: Use a dummy account. Do not use your primary LinkedIn account.\n")
    
    test_keyword = "hiring data scientist egypt"
    posts = scrape_linkedin_posts(test_keyword)
    
    if posts:
        print("\n--- Sample Posts Found ---")
        for i, post in enumerate(posts[:3]):
            print(f"\n📝 Post #{i+1}:")
            print(post["text"][:300] + "..." if len(post["text"]) > 300 else post["text"])
    else:
        print("\nNo posts found or authentication failed.")
