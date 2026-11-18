import os
import sys
import time
import threading
import subprocess
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
        get_edge_binary_path,
        get_clean_browser_page,
    )
    USER_DATA_DIR = get_browser_user_data_dir()
except Exception:
    USER_DATA_DIR = os.path.join(BASE_DIR, "playwright_profile")
    get_browser_launch_kwargs = None
    get_chrome_binary_path = None
    get_edge_binary_path = None
    get_clean_browser_page = None

if get_clean_browser_page is None:
    def get_clean_browser_page(context):
        pages = list(getattr(context, "pages", []))
        if not pages:
            return context.new_page()
        primary_page = pages[0]
        for old_page in pages[1:]:
            try:
                old_page.close()
            except Exception:
                pass
        return primary_page

os.makedirs(USER_DATA_DIR, exist_ok=True)

# Master directory of supported platforms for job searching, scraping, and applications
SUPPORTED_SITES = {
    "linkedin": {
        "name": "LinkedIn",
        "url": "https://www.linkedin.com/login",
    },
    "tanqeeb": {
        "name": "Tanqeeb",
        "url": "https://egypt.tanqeeb.com/users/login",
    },
    "glassdoor": {
        "name": "Glassdoor",
        "url": "https://www.glassdoor.com/member/home/index.htm",
    },
    "bayt": {
        "name": "Bayt",
        "url": "https://www.bayt.com/en/my-workspace/",
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
        "--disable-dev-shm-usage",
        "--disable-quic",
        "--ignore-certificate-errors",
        "--disable-features=EncryptedClientHello,UseDnsHttpsSvcbAlpn,DnsOverHttps,msEdgeSingleSignOn,msEdgeAutoSignIn,msImplicitSignIn",
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
        [
            "--enable-automation",
            "--enable-blink-features=IdleDetection",
            "--disable-extensions",
            "--disable-component-update",
        ],
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

    # 1. Attempt using project-configured launch kwargs (e.g. Edge)
    if get_browser_launch_kwargs:
        try:
            cfg_kwargs = get_browser_launch_kwargs()
            return playwright_instance.chromium.launch_persistent_context(
                **{**launch_args, **cfg_kwargs}
            )
        except Exception:
            pass

    # 2. Attempt Edge channel explicitly
    try:
        return playwright_instance.chromium.launch_persistent_context(
            channel="msedge",
            **launch_args,
        )
    except Exception:
        pass

    # 3. Attempt local Chrome binary if present
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

    # 4. Fallback across system channels
    for ch in ["chrome", None]:
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


def launch_native_edge_login(targets: dict, profile_name: str | None = None) -> bool:
    """
    Launches Microsoft Edge natively with the designated profile ('job_agent').
    Opens the user's authentic Edge browser environment, preserving all native profiles
    (Job_agent, Influencetargetingmarketing, Mohamed), extensions, and clean UI without
    unsupported automation flags.
    """
    profile = profile_name or os.getenv("EDGE_PROFILE_DIRECTORY", "job_agent")
    edge_bin = None
    if get_edge_binary_path:
        try:
            edge_bin = get_edge_binary_path()
        except Exception:
            pass

    if not edge_bin:
        for standard in [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]:
            if os.path.exists(standard):
                edge_bin = standard
                break

    if not edge_bin or not os.path.exists(edge_bin):
        return False

    urls = [site["url"] for site in targets.values()]
    cmd = [edge_bin, f"--profile-directory={profile}"] + urls

    print("=" * 60)
    print(f"🌐 Launching Microsoft Edge natively with profile '{profile}'...")
    print("=" * 60)
    try:
        subprocess.Popen(cmd)
        print("✅ Edge has opened with your requested platform login tabs.")
        print("Log in to your platforms in the browser window.")
        print("Press ENTER in this console once you have finished logging in...")
        print("=" * 60)
        try:
            input()
        except Exception:
            pass
        try:
            from core.auth_status import sync_profile_storage
            sync_profile_storage(USER_DATA_DIR)
        except Exception:
            pass
        return True
    except Exception as e:
        print(f"Native Edge launch failed ({e}), falling back to Playwright...")
        return False


def multi_login(selected_keys: list[str] | None = None, prefer_native: bool = True):
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

    # For interactive use (Settings UI and terminal), prefer launching Edge natively so the user's authentic
    # profile ecosystem, extensions (Plucky), and multi-profile switcher are preserved without --no-sandbox flags.
    if prefer_native and not os.getenv("PYTEST_CURRENT_TEST"):
        if launch_native_edge_login(targets):
            return

    print("Launching browser via Playwright...")

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

        # Ensure only a single fresh page remains and close any extra default/restored startup tabs
        primary_page = get_clean_browser_page(context)

        pages = []
        for i, (key, site) in enumerate(targets.items()):
            if i == 0:
                page = primary_page
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
        print(f"• All session cookies will remain safely preserved in persistent profile ({os.path.basename(USER_DATA_DIR)}).")
        print("\n👉 Press [ENTER] in this terminal when finished (or close the browser window).")
        print("*" * 60 + "\n")

        wait_for_user_completion(context)

        try:
            context.close()
        except Exception:
            pass

        try:
            from core.auth_status import sync_profile_storage
            sync_profile_storage(USER_DATA_DIR)
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
