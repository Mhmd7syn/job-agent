import os
import contextlib
from seleniumbase import Driver
from core.config import get_chrome_binary_path

@contextlib.contextmanager
def SeleniumSession():
    """
    Yields a SeleniumBase Undetected Chromedriver (UC) instance.
    Uses Chrome for Testing binary to avoid requiring a global Chrome installation.
    """
    driver = None
    try:
        chrome_bin = get_chrome_binary_path()
        if not chrome_bin:
            print("Warning: Chrome binary not found. Falling back to default.")
            
        # Use UC Mode to bypass Cloudflare Turnstile with flags compatible with domain-level filtering
        driver = Driver(
            uc=True,
            headless=True,
            binary_location=chrome_bin,
            disable_features="EncryptedClientHello,UseDnsHttpsSvcbAlpn,DnsOverHttps",
            chromium_arg="disable-async-dns,disable-quic,disable-background-networking,disable-sync",
        )
        yield driver
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
