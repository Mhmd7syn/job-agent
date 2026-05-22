import os
from playwright.sync_api import sync_playwright

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USER_DATA_DIR = os.path.join(BASE_DIR, "playwright_profile")

def login():
    print("🚀 Launching Playwright browser in headed mode...")
    print(f"📂 Profile will be saved to: {USER_DATA_DIR}")
    print("\n👉 INSTRUCTIONS:")
    print("1. A browser window will open.")
    print("2. Log into your LinkedIn dummy account manually.")
    print("3. Once you see the LinkedIn feed and are fully logged in, close the browser window.")
    print("4. Your session will be saved persistently!")
    
    with sync_playwright() as p:
        # Launch persistent context
        context = p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=False
        )

        
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://www.linkedin.com/login")
        
        # Wait until the user closes the browser window manually
        try:
            page.wait_for_event("close", timeout=0)
        except Exception:
            pass

    print("✅ Browser closed. Your session has been saved.")
    print("You no longer need to update LINKEDIN_LI_AT in .env!")

if __name__ == "__main__":
    login()
