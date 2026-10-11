import re
import html
from typing import Optional, Dict, Any
from core.applicant_profile import load_profile


def get_signature_from_config(profile: Optional[Dict[str, Any]] = None) -> str:
    """
    Retrieves the signature directly from the candidate profile configuration.
    No hardcoded data, external files, or filesystem lookups.
    """
    if profile is None:
        profile = load_profile()
    return profile.get("auto_apply_settings", {}).get("email_signature_personal", "").strip()


def strip_signoff_from_body(body: str) -> str:
    """
    Removes any trailing sign-off block from the email body
    to prevent duplicate sign-offs when the signature from configuration is appended.
    """
    if not body:
        return ""
    pattern = r"(?i)\n\s*(?:best\s+regards|sincerely|kind\s+regards|regards|warm\s+regards)[\s,:].*$"
    return re.sub(pattern, "", body, flags=re.DOTALL).rstrip()


def format_email_body_html(body_text: str, signature: Optional[str] = None) -> str:
    """
    Formats the email body into clean HTML paragraphs and bullet lists,
    and appends the signature directly from configuration with its format and style preserved.
    """
    sig = signature if signature is not None else get_signature_from_config()
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
        # If signature is already HTML, keep it directly; otherwise convert text format preserving newlines
        if any(tag in sig.lower() for tag in ("<p", "<div", "<table", "<span")):
            sig_html = sig
        else:
            # Preserve exact spacing and line breaks of normal text signature from configuration
            sig_lines = sig.split("\n")
            rendered_lines = [html.escape(line) if line.strip() else "&nbsp;" for line in sig_lines]
            sig_html = (
                f"<div style='font-family: Aptos, Calibri, sans-serif; font-size: 11pt; color: #1e293b; margin-top: 14pt; line-height: 1.45;'>"
                f"{'<br/>'.join(rendered_lines)}</div>"
            )

        return (
            f"<html><head><meta http-equiv='Content-Type' content='text/html; charset=utf-8'></head>"
            f"<body style='font-family: Aptos, Calibri, sans-serif; font-size: 11pt; color: #1e293b;'>"
            f"{body_html}<br/>{sig_html}</body></html>"
        )

    return body_html
