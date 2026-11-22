import os
import re
import html
import logging
from html.parser import HTMLParser
from typing import Optional, Dict, Any
from core.applicant_profile import load_profile

logger = logging.getLogger(__name__)


class _HTMLToTextExtractor(HTMLParser):
    """
    Extracts structured, human-readable plain text from an HTML signature block.
    Extracts table layout, breaks, and image alt attributes (e.g. LinkedIn, GitHub, Kaggle).
    """
    def __init__(self):
        super().__init__()
        self.pieces = []

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t in ("p", "br", "tr", "div", "h1", "h2", "h3", "h4", "h5", "h6"):
            self.pieces.append("\n")
        elif t == "td":
            self.pieces.append("  ")
        elif t == "img":
            attrs_dict = dict(attrs)
            alt = attrs_dict.get("alt", "").strip()
            if alt:
                self.pieces.append(f" {alt} ")

    def handle_endtag(self, tag):
        t = tag.lower()
        if t in ("p", "tr", "div", "table"):
            self.pieces.append("\n")

    def handle_data(self, data):
        self.pieces.append(data)

    def get_text(self) -> str:
        raw = "".join(self.pieces)
        raw = html.unescape(raw)
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in raw.split("\n")]
        cleaned = []
        for line in lines:
            if line:
                cleaned.append(line)
        return "\n".join(cleaned).strip()


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _role_matches(configured_role: str, target_role: str) -> bool:
    """Checks whether a configured role name matches a target role query."""
    if not configured_role or not target_role:
        return False
    cr = configured_role.strip().lower()
    tr = target_role.strip().lower()
    if cr == tr or cr in tr or tr in cr:
        return True

    cr_words = {w for w in re.split(r"[\s&/,\-\+_]+", cr) if len(w) >= 3 and w not in {"and", "the", "for"}}
    tr_words = {w for w in re.split(r"[\s&/,\-\+_]+", tr) if len(w) >= 3 and w not in {"and", "the", "for"}}
    common = cr_words & tr_words
    if len(common) >= 2:
        return True
    if len(common) == 1:
        word = next(iter(common))
        if len(word) >= 5 or word in ("data", "stem", "bi"):
            return True
    return False


def get_signature_path_from_config(
    profile: Optional[Dict[str, Any]] = None,
    target_role: Optional[str] = None
) -> str:
    """
    Retrieves the HTML signature file path from candidate profile configuration.
    Supports role-specific signatures with fallback to global configuration and default signature.html files.
    """
    if profile is None:
        profile = load_profile()

    auto_apply = profile.get("auto_apply_settings", {})
    smart_screen = profile.get("smart_screening", {})

    # 1. Role-specific signature check
    if target_role:
        # Check signatures_by_role in auto_apply_settings or smart_screening
        sig_by_role = auto_apply.get("signatures_by_role", {}) or smart_screen.get("signatures_by_role", {})
        for role_key, path in sig_by_role.items():
            if _role_matches(role_key, target_role):
                if path and str(path).strip():
                    return str(path).strip()

        # Check ROLES in core.config
        try:
            import core.config as app_config
            roles = getattr(app_config, "ROLES", [])
            for r in roles:
                role_title = r.get("title", "").strip()
                if _role_matches(role_title, target_role):
                    sig_p = r.get("signature_path", "")
                    if sig_p and str(sig_p).strip():
                        return str(sig_p).strip()
        except Exception:
            pass

    # 2. Global configured signature path
    global_path = auto_apply.get("email_signature_path", "").strip()
    if global_path:
        return global_path

    # 3. Default auto-discovery for signature.html in project root or data/ directory
    candidate_default_paths = [
        os.path.join(BASE_DIR, "signature.html"),
        os.path.join(BASE_DIR, "data", "signature.html"),
    ]
    for p in candidate_default_paths:
        if os.path.exists(p):
            return p

    return ""


def get_signature_html(
    profile: Optional[Dict[str, Any]] = None,
    signature_path: Optional[str] = None,
    target_role: Optional[str] = None
) -> str:
    """
    Loads and extracts the HTML signature from the configured path.
    Supports role-specific overrides, inner body/table extraction, and legacy fallback.
    """
    if profile is None:
        profile = load_profile()

    path = signature_path or get_signature_path_from_config(profile, target_role=target_role)

    if path and os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

            # Extract body content if wrapped in full HTML document
            body_match = re.search(r"<body[^>]*>(.*?)</body>", content, re.DOTALL | re.IGNORECASE)
            if body_match:
                extracted = body_match.group(1).strip()
            else:
                extracted = content.strip()

            return extracted
        except Exception as e:
            logger.error(f"Error reading HTML signature from '{path}': {e}")

    # Fallback to legacy string if present
    legacy_sig = profile.get("auto_apply_settings", {}).get("email_signature_personal", "").strip()
    return legacy_sig


def get_signature_text(
    profile: Optional[Dict[str, Any]] = None,
    target_role: Optional[str] = None
) -> str:
    """
    Converts the HTML signature into a clean plain text representation for plain text email bodies or fallbacks.
    """
    sig_html = get_signature_html(profile, target_role=target_role)
    if not sig_html:
        return ""

    if any(tag in sig_html.lower() for tag in ("<table", "<div", "<p", "<tr", "<td", "<br")):
        extractor = _HTMLToTextExtractor()
        extractor.feed(sig_html)
        text = extractor.get_text()
        return text

    return sig_html.strip()


def get_signature_from_config(
    profile: Optional[Dict[str, Any]] = None,
    target_role: Optional[str] = None
) -> str:
    """
    Retrieves the signature from configuration. Returns the HTML signature if available,
    falling back to plain text.
    """
    html_sig = get_signature_html(profile, target_role=target_role)
    if html_sig:
        return html_sig
    return get_signature_text(profile, target_role=target_role)


def strip_signoff_from_body(body: str) -> str:
    """
    Removes any trailing sign-off block from the email body
    to prevent duplicate sign-offs when the signature from configuration is appended.
    """
    if not body:
        return ""
    pattern = r"(?i)\n\s*(?:best\s+regards|kind\s+regards|warm\s+regards|with\s+regards|regards|sincerely|warmly|cheers|best|thanks|thank\s+you|respectfully)[\s,:].*$"
    return re.sub(pattern, "", body, flags=re.DOTALL).rstrip()


def format_email_body_html(
    body_text: str,
    signature: Optional[str] = None,
    append_signature: bool = True,
    target_role: Optional[str] = None,
    **kwargs
) -> str:
    """
    Formats the email body into clean HTML paragraphs and bullet lists,
    and appends the HTML signature directly from the configured file path with its format and style preserved.
    """
    if not append_signature:
        sig = ""
    else:
        sig = signature if signature is not None else get_signature_html(target_role=target_role)

    body_clean = strip_signoff_from_body(body_text) if sig else body_text.strip()
    paragraphs = re.split(r"\n\s*\n", body_clean.strip())

    html_parts = []
    for p in paragraphs:
        p_str = p.strip()
        if not p_str:
            continue
        lines = [l.strip() for l in p_str.split("\n") if l.strip()]
        bullet_indices = [i for i, l in enumerate(lines) if l.startswith(("•", "-", "*"))]
        if bullet_indices:
            first_b = bullet_indices[0]
            lead_lines = lines[:first_b]
            bullet_lines = lines[first_b:]
            if lead_lines:
                lead_escaped = "<br/>".join(html.escape(l) for l in lead_lines)
                html_parts.append(
                    f"<p style='margin-top: 0; margin-bottom: 6pt; font-family: Aptos, Calibri, sans-serif; "
                    f"font-size: 11pt; color: #1e293b; line-height: 1.5;'>{lead_escaped}</p>"
                )
            items = []
            for l in bullet_lines:
                clean_item = re.sub(r"^[•\-*]\s*", "", l)
                items.append(f"<li style='margin-bottom: 4px;'>{html.escape(clean_item)}</li>")
            html_parts.append(
                f"<ul style='margin-top: 4pt; margin-bottom: 12pt; padding-left: 20px; "
                f"font-family: Aptos, Calibri, sans-serif; font-size: 11pt; color: #1e293b; line-height: 1.5;'>"
                f"{''.join(items)}</ul>"
            )
        else:
            p_escaped = "<br/>".join(html.escape(l) for l in lines)
            html_parts.append(
                f"<p style='margin-top: 0; margin-bottom: 12pt; font-family: Aptos, Calibri, sans-serif; "
                f"font-size: 11pt; color: #1e293b; line-height: 1.5;'>{p_escaped}</p>"
            )

    body_html = "\n".join(html_parts)

    if sig:
        if any(tag in sig.lower() for tag in ("<p", "<div", "<table", "<span")):
            # If already contains full html tags, ensure body wrapper only if not present
            body_match = re.search(r"<body[^>]*>(.*?)</body>", sig, re.DOTALL | re.IGNORECASE)
            sig_html = (body_match.group(1).strip() if body_match else sig).strip()
        else:
            sig_lines = sig.strip().split("\n")
            rendered_lines = [html.escape(line) if line.strip() else "&nbsp;" for line in sig_lines]
            sig_html = (
                f"<div style='font-family: Aptos, Calibri, sans-serif; font-size: 11pt; color: #1e293b; line-height: 1.45;'>"
                f"{'<br/>'.join(rendered_lines)}</div>"
            )

        return (
            f"<html><head><meta http-equiv='Content-Type' content='text/html; charset=utf-8'></head>"
            f"<body style='font-family: Aptos, Calibri, sans-serif; font-size: 11pt; color: #1e293b;'>"
            f"{body_html}\n{sig_html}</body></html>"
        )

    return body_html
