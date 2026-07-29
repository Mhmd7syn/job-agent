import os
import time
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # Project root
USER_DATA_DIR = os.path.join(BASE_DIR, "playwright_profile")
os.makedirs(USER_DATA_DIR, exist_ok=True)

def launch_persistent_browser(playwright_instance, user_data_dir, headless=False, **kwargs):
    channels = ["chrome", "msedge", None]
    default_args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-infobars",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-quic",
        "--ignore-certificate-errors",
    ]
    if not headless:
        default_args.append("--start-maximized")
    else:
        default_args.append("--window-size=1920,1080")
        
    custom_args = kwargs.pop("args", [])
    combined_args = list(set(default_args + custom_args))
    
    ignore_default_args = kwargs.pop("ignore_default_args", ["--enable-automation", "--enable-blink-features=IdleDetection"])
    viewport = kwargs.pop("viewport", None)

    for channel in channels:
        try:
            launch_args = {
                "user_data_dir": user_data_dir,
                "headless": headless,
                "args": combined_args,
                "ignore_default_args": ignore_default_args,
                "viewport": viewport,
                **kwargs
            }
            if channel:
                launch_args["channel"] = channel
            return playwright_instance.chromium.launch_persistent_context(**launch_args)
        except Exception:
            continue
    raise RuntimeError("Could not launch Chrome, Edge, or Chromium.")

def manual_login():
    print("Launching browser for manual login...")
    print("Please log in and solve any security checks.")
    
    with sync_playwright() as p:
        context = launch_persistent_browser(
            p,
            user_data_dir=USER_DATA_DIR,
            headless=False
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            Stealth().apply_stealth_sync(page)
        except Exception as e:
            print(f"Notice: Stealth application skipped ({e})")
        
        try:
            page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"\nNotice: Initial navigation experienced an interruption ({str(e).splitlines()[0]}). Retrying via homepage...")
            time.sleep(3)
            page.goto("https://www.linkedin.com/", wait_until="domcontentloaded", timeout=60000)
        
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
