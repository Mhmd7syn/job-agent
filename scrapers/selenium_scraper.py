import os
import contextlib
from seleniumbase import Driver

@contextlib.contextmanager
def SeleniumSession():
    """
    Yields a SeleniumBase Undetected Chromedriver (UC) instance.
    Uses the local Chrome for Testing binary to avoid requiring a global Chrome installation.
    """
    driver = None
    try:
        # Resolve path to the local chrome-win64 directory
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        chrome_bin = os.path.join(base_dir, "chrome-win64", "chrome.exe")
        
        if not os.path.exists(chrome_bin):
            print(f"Warning: Local Chrome binary not found at {chrome_bin}. Falling back to default.")
            chrome_bin = None
            
        # Use UC Mode to bypass Cloudflare Turnstile
        driver = Driver(uc=True, headless=True, binary_location=chrome_bin)
        yield driver
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
