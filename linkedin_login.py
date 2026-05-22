import os
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USER_DATA_DIR = os.path.join(BASE_DIR, "playwright_profile")

def manual_login():
    print("Launching browser for manual login...")
    print("Please log in and solve any security checks.")
    
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=False,
            args=["--start-maximized"]
        )
        page = context.pages[0] if context.pages else context.new_page()
        Stealth().apply_stealth_sync(page)
        
        page.goto("https://www.linkedin.com/login")
        
        print("\n" + "*" * 50)
        print("Waiting for you to log in...")
        print("Please complete any captchas or security challenges.")
        print("When you have successfully logged in and see your LinkedIn feed, simply CLOSE THE BROWSER WINDOW.")
        print("*" * 50 + "\n")
        
        try:
            # Wait indefinitely until the user closes the browser
            page.wait_for_event("close", timeout=0)
        except Exception:
            pass
            
        context.close()
        print("Browser closed. Session saved successfully. You can now run job_agent.py again.")

if __name__ == "__main__":
    manual_login()
