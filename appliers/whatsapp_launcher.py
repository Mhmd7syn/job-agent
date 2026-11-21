import os
import sys
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from appliers.gmail_launcher import copy_file_to_clipboard
from appliers.whatsapp_copilot import normalize_phone_number, build_wa_me_url, build_whatsapp_web_url
from core.config import open_edge_browser


def launch_whatsapp_web(
    phone: str,
    pitch: str,
    cv_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Launches WhatsApp Web natively in Microsoft Edge using the authentic 'job_agent' persistent profile.
    1. Copies the candidate's matched CV PDF to the Windows clipboard (CF_HDROP) for instant Ctrl+V attachment.
    2. Opens Edge natively via open_edge_browser with --profile-directory=job_agent.
    3. Pre-fills the formatted multi-paragraph pitch message directly into the WhatsApp Web message box.
    """
    clean_phone = normalize_phone_number(phone)
    web_url = build_whatsapp_web_url(clean_phone, pitch)
    wa_me_url = build_wa_me_url(clean_phone, pitch)

    cv_copied = False
    if cv_path and os.path.exists(cv_path):
        cv_copied = copy_file_to_clipboard(cv_path)

    # Launch native Edge strictly with the user's authentic job_agent profile
    try:
        launched = open_edge_browser(web_url, profile_name="job_agent")
        if not launched:
            import webbrowser
            webbrowser.open(web_url)
            launched = True
    except Exception as e:
        logger.error(f"Failed to open WhatsApp Web URL in Edge: {e}")
        launched = False

    return {
        "status": "success" if launched else "error",
        "launched_via": "edge_job_agent",
        "phone": clean_phone,
        "web_url": web_url,
        "wa_me_url": wa_me_url,
        "cv_copied_to_clipboard": cv_copied,
        "cv_filename": os.path.basename(cv_path) if cv_path else None,
        "cv_path": cv_path
    }
