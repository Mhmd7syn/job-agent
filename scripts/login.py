import os
import sys
import time
import threading
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

# Ensure project root is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

try:
    from core.config import (
        get_browser_user_data_dir,
        get_browser_launch_kwargs,
        get_chrome_binary_path,
    )
    USER_DATA_DIR = get_browser_user_data_dir()
except Exception:
    USER_DATA_DIR = os.path.join(BASE_DIR, "playwright_profile")
    get_browser_launch_kwargs = None
    get_chrome_binary_path = None

os.makedirs(USER_DATA_DIR, exist_ok=True)

# Master directory of supported platforms for job searching, scraping, and applications
SUPPORTED_SITES = {
    "linkedin": {
        "name": "LinkedIn",
        "url": "https://www.linkedin.com/login",
    },
    "tanqeeb": {
        "name": "Tanqeeb",
        "url": "https://egypt.tanqeeb.com/en/login",
    },
    "glassdoor": {
        "name": "Glassdoor",
        "url": "https://www.glassdoor.com/profile/login_input.htm",
    },
    "bayt": {
        "name": "Bayt",
        "url": "https://www.bayt.com/en/login/",
    },
    "wuzzuf": {
        "name": "Wuzzuf",
        "url": "https://wuzzuf.net/login",
    },
    "indeed": {
        "name": "Indeed",
        "url": "https://secure.indeed.com/account/login",
    },
    "whatsapp": {
        "name": "WhatsApp Web",
        "url": "https://web.whatsapp.com/",
    },
}


def launch_persistent_browser(playwright_instance, user_data_dir, headless=False, **kwargs):
    """
    Launches a persistent browser context (Chrome/Edge) using the shared profile.
    Retains all saved cookies, sessions, and local storage across runs.
    """
    default_args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-infobars",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-quic",
        "--ignore-certificate-errors",
        "--disable-features=EncryptedClientHello,UseDnsHttpsSvcbAlpn,DnsOverHttps",
        "--disable-async-dns",
        "--disable-background-networking",
        "--disable-sync",
        "--disable-default-apps",
        "--no-restore-session-state",
        "--disable-session-crashed-bubble",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if not headless:
        default_args.append("--start-maximized")
    else:
        default_args.append("--window-size=1920,1080")

    custom_args = kwargs.pop("args", [])
    combined_args = list(set(default_args + custom_args))

    ignore_default_args = kwargs.pop(
        "ignore_default_args",
        ["--enable-automation", "--enable-blink-features=IdleDetection"],
    )
    viewport = kwargs.pop("viewport", None)

    launch_args = {
        "user_data_dir": user_data_dir,
        "headless": headless,
        "args": combined_args,
        "ignore_default_args": ignore_default_args,
        "viewport": viewport,
        **kwargs,
    }

    # 1. Attempt using dedicated Chrome binary if present (e.g. C:\automation\chrome-win64\chrome.exe)
    chrome_bin = None
    if get_chrome_binary_path:
        try:
            chrome_bin = get_chrome_binary_path()
        except Exception:
            pass
    if not chrome_bin:
        c_bin = r"C:\automation\chrome-win64\chrome.exe"
        if os.path.exists(c_bin):
            chrome_bin = c_bin

    if chrome_bin:
        try:
            return playwright_instance.chromium.launch_persistent_context(
                executable_path=chrome_bin,
                **launch_args,
            )
        except Exception:
            pass

    # 2. Attempt using project-configured launch kwargs (e.g. Edge)
    if get_browser_launch_kwargs:
        try:
            cfg_kwargs = get_browser_launch_kwargs()
            return playwright_instance.chromium.launch_persistent_context(
                **{**launch_args, **cfg_kwargs}
            )
        except Exception:
            pass

    # 3. Fallback across system channels
    for ch in ["chrome", "msedge", None]:
        try:
            fb_args = dict(launch_args)
            if ch:
                fb_args["channel"] = ch
            return playwright_instance.chromium.launch_persistent_context(**fb_args)
        except Exception:
            continue

    raise RuntimeError(
        "Could not launch browser. Ensure Chrome or Edge is installed and not currently locked by another process."
    )


def wait_for_user_completion(context):
    """
    Waits until the user either presses ENTER in the terminal or closes all browser windows.
    """
    stop_event = threading.Event()

    def _stdin_listener():
        try:
            input()
        except Exception:
            pass
        finally:
            stop_event.set()

    t = threading.Thread(target=_stdin_listener, daemon=True)
    t.start()

    while not stop_event.is_set():
        try:
            pages = context.pages
            if not pages:
                print("\nBrowser tabs closed by user.")
                break
            # Keepalive ping to check context validity
            pages[0].evaluate("1 + 1")
        except Exception:
            print("\nBrowser window closed by user.")
            break
        time.sleep(1)


def multi_login(selected_keys: list[str] | None = None):
    """
    Opens target platforms in separate tabs within the persistent browser profile.
    Existing sessions and cookies are preserved. New logins are saved upon closing.
    """
    if selected_keys:
        targets = {k: v for k, v in SUPPORTED_SITES.items() if k in selected_keys}
    else:
        targets = SUPPORTED_SITES

    print("=" * 60)
    print("🌐 Persistent Multi-Platform Login Manager")
    print(f"📁 Profile Directory: {USER_DATA_DIR}")
    print("=" * 60)
    print("Opening the following sites:")
    for key, site in targets.items():
        print(f"  • {site['name']} -> {site['url']}")
    print("=" * 60)
    print("Launching browser...")

    with sync_playwright() as p:
        try:
            context = launch_persistent_browser(
                p,
                user_data_dir=USER_DATA_DIR,
                headless=False,
            )
        except Exception as e:
            print(f"\n❌ Error launching browser: {e}")
            print("Tip: If Chrome/Edge is already running with this profile, close it and retry.")
            return

        pages = []
        for i, (key, site) in enumerate(targets.items()):
            if i == 0:
                page = context.pages[0] if context.pages else context.new_page()
            else:
                page = context.new_page()

            try:
                Stealth().apply_stealth_sync(page)
            except Exception:
                pass

            print(f"Opening tab [{i+1}/{len(targets)}]: {site['name']}...")
            try:
                page.goto(site["url"], wait_until="domcontentloaded", timeout=45000)
            except Exception as e:
                print(f"  Notice: Navigation to {site['name']} timed out or interrupted ({e}).")

            pages.append(page)

        # Focus the primary tab
        if pages:
            try:
                pages[0].bring_to_front()
            except Exception:
                pass

        print("\n" + "*" * 60)
        print("✅ Browser is ready with all platforms loaded.")
        print("• If you are already logged in, your active session is active.")
        print("• Log in or solve any security/CAPTCHA challenges for needed accounts.")
        print("• All session cookies will remain safely preserved in playwright_profile.")
        print("\n👉 Press [ENTER] in this terminal when finished (or close the browser window).")
        print("*" * 60 + "\n")

        wait_for_user_completion(context)

        try:
            context.close()
        except Exception:
            pass

        print("\n✅ Browser closed. All session tokens and cookies have been saved successfully.")
        print("You can now run job_agent.py or individual scrapers without logging in again.")


def main():
    args = [arg.strip().lower().lstrip("-") for arg in sys.argv[1:]]

    if "help" in args or "h" in args:
        print("Usage: python scripts/login.py [site1 site2 ...]")
        print("\nSupported sites:")
        for k, v in SUPPORTED_SITES.items():
            print(f"  - {k} ({v['name']})")
        print("\nIf no sites are specified, all platforms are opened automatically.")
        return

    # Check for requested site filters
    requested = [arg for arg in args if arg in SUPPORTED_SITES]
    if args and not requested:
        print(f"⚠️ Unrecognized sites: {', '.join(args)}")
        print(f"Available sites: {', '.join(SUPPORTED_SITES.keys())}")
        return

    multi_login(selected_keys=requested if requested else None)


if __name__ == "__main__":
    main()
