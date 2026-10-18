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


def get_signature_path_from_config(profile: Optional[Dict[str, Any]] = None) -> str:
    """
    Retrieves the HTML signature file path from candidate profile configuration.
    """
    if profile is None:
        profile = load_profile()
    return profile.get("auto_apply_settings", {}).get("email_signature_path", "").strip()


def get_signature_html(
    profile: Optional[Dict[str, Any]] = None,
    signature_path: Optional[str] = None
) -> str:
    """
    Loads and extracts the HTML signature from the configured path.
    Extracts the inner body / table structure cleanly so it can be embedded into email drafts.
    """
    if profile is None:
        profile = load_profile()

    path = signature_path or get_signature_path_from_config(profile)

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


def get_signature_text(profile: Optional[Dict[str, Any]] = None) -> str:
    """
    Converts the HTML signature into a clean plain text representation for plain text email bodies or fallbacks.
    """
    sig_html = get_signature_html(profile)
    if not sig_html:
        return ""

    if any(tag in sig_html.lower() for tag in ("<table", "<div", "<p", "<tr", "<td", "<br")):
        extractor = _HTMLToTextExtractor()
        extractor.feed(sig_html)
        text = extractor.get_text()
        return text

    return sig_html.strip()


def get_signature_from_config(profile: Optional[Dict[str, Any]] = None) -> str:
    """
    Retrieves the signature from configuration. Returns the HTML signature if available,
    falling back to plain text.
    """
    html_sig = get_signature_html(profile)
    if html_sig:
        return html_sig
    return get_signature_text(profile)


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
    **kwargs
) -> str:
    """
    Formats the email body into clean HTML paragraphs and bullet lists,
    and appends the HTML signature directly from the configured file path with its format and style preserved.
    """
    if not append_signature:
        sig = ""
    else:
        sig = signature if signature is not None else get_signature_html()

    body_clean = strip_signoff_from_body(body_text) if sig else body_text.strip()
    paragraphs = re.split(r"\n\s*\n", body_clean.strip())

    html_parts = []
    for p in paragraphs:
        p_str = p.strip()
        if not p_str:
            continue
        lines = [l.strip() for l in p_str.split("\n") if l.strip()]
        if lines and all(l.startswith(("•", "-", "*")) for l in lines):
            items = []
            for l in lines:
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
