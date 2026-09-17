import re
import hashlib
from datetime import date, datetime, timedelta
from typing import Any, Optional, Dict, List, Tuple
import pandas as pd

GENERIC_COMPANY_NAMES = {
    'nan', 'confidential', 'unknown', 'not specified', 'not mentioned',
    'staffing and recruiting', 'client', 'our client', 'a leading client',
    'our multinational client', 'the company', 'reputable company', 'leading company'
}


def make_job_id(title: str, company: str, job_url: str = "") -> str:
    """
    Generates a clean, deterministic unique ID for the job.
    Falls back to hashing url/name if the normalized text is too short.
    """
    t = re.sub(r'[^\w\s]', ' ', str(title or '').lower()).strip()
    c = re.sub(r'[^\w\s]', ' ', str(company or '').lower()).strip()
    jid = f"{re.sub(r'\s+', ' ', t)}|{re.sub(r'\s+', ' ', c)}"
    if len(jid.replace('|', '').strip()) < 3:
        raw_fallback = job_url or f"{title}_{company}"
        h = hashlib.md5(raw_fallback.encode('utf-8')).hexdigest()[:12]
        jid = f"job_{h}"
    return jid


def normalize_job_type(raw_type: str = "", title: str = "", desc: str = "", is_scholarship: bool = False) -> str:
    """
    Normalizes job type into standard categories:
    'Scholarship', 'Internship', 'Part-time', 'Contract', 'Full-time', or 'Not specified'.
    """
    if is_scholarship:
        return "Scholarship"
    rt = str(raw_type or "").lower().strip()
    t = str(title or "").lower().strip()
    d = str(desc or "").lower().strip()
    combined = f"{rt} {t} {d}"

    if any(k in combined for k in ["scholarship", "fellowship", "منحة", "منح", "grant"]):
        return "Scholarship"
    if any(k in combined for k in ["intern", "internship", "trainee", "working student"]):
        return "Internship"
    if any(k in combined for k in ["part time", "part-time", "دوام جزئي"]):
        return "Part-time"
    if any(k in combined for k in ["contract", "freelance", "عقد", "حر"]):
        return "Contract"
    if any(k in combined for k in ["full time", "full-time", "دوام كامل", "permanent"]):
        return "Full-time"
    if rt in ["", "nan", "none", "not specified", "unknown"]:
        return "Not specified"
    return rt.title()


def normalize_is_remote(location: str = "", title: str = "", desc: str = "", job_type: str = "", raw_is_remote: Any = False) -> bool:
    """
    Determines whether a job is remote based on boolean flag or English/Arabic keywords.
    """
    if raw_is_remote is True or str(raw_is_remote).lower() in ("true", "1"):
        return True
    combined = f"{location} {title} {desc} {job_type}".lower()
    remote_kws = ["remote", "work from home", "عن بعد", "العمل من المنزل", "telecommute", "wfh"]
    return any(k in combined for k in remote_kws)


def extract_company_from_desc(desc: str) -> str:
    """
    Attempts regex extraction of real company names if marked Confidential or Unknown.
    """
    if not desc:
        return ""
    # Pattern 1: "[Company] is looking/seeking/hiring/recruiting for..."
    match = re.search(r'\b([A-Z][A-Za-z0-9\.\-\s&]{1,30}?)\s+(?:is\s+)?(?:looking|seeking|hiring|searching|recruiting)\s+(?:for|to|a|an)\b', desc[:800])
    if match:
        extracted = match.group(1).strip()
        ignore_words = {'we', 'our', 'the', 'this', 'here', 'currently', 'an', 'a', 'our client', 'client', 'someone', 'who', 'they', 'he', 'she'}
        if extracted.lower() not in ignore_words and not any(gw in extracted.lower() for gw in ['our client', 'leading client', 'multinational', 'reputable company']):
            return extracted

    # Pattern 2: "About [Company]..."
    match_about = re.search(r'(?:^|\n|\.\s+)\s*About\s+([A-Z][A-Za-z0-9\.\-\s&]{2,30}?)(?:\s*:|\s*\.|\s*\n|\s+is|\s+was|\s+-)', desc)
    if match_about:
        extracted = match_about.group(1).strip()
        if extracted.lower() not in {'this job', 'the role', 'us', 'our company', 'the company', 'the position', 'the team', 'the client'} and not any(gw in extracted.lower() for gw in ['our client', 'leading client']):
            return extracted

    return ""


def normalize_company(company: str = "", desc: str = "") -> str:
    """
    Cleans company name, strips generic placeholders, and extracts from description if needed.
    """
    c = str(company or "").strip()
    if not c or c.lower() in GENERIC_COMPANY_NAMES:
        extracted = extract_company_from_desc(desc)
        if extracted:
            return extracted
        return "Unknown" if not c else c.title()
    return c


def parse_job_date(date_val: Any) -> str:
    """
    Normalizes dates to standard YYYY-MM-DD string.
    Supports datetime/date objects, ISO strings, and relative time expressions
    (e.g., '5 days ago', '1 week ago', '2 months ago', 'yesterday', 'أمس', 'اليوم').
    """
    today = date.today()
    if date_val is None or (isinstance(date_val, float) and pd.isna(date_val)):
        return today.isoformat()
    if isinstance(date_val, (datetime, date)):
        return date_val.strftime("%Y-%m-%d")

    ds = str(date_val).strip().lower()
    if not ds or ds in ('nan', 'none', 'nat'):
        return today.isoformat()

    try:
        # Direct ISO match (YYYY-MM-DD)
        m_iso = re.search(r'(\d{4}-\d{2}-\d{2})', ds)
        if m_iso:
            return m_iso.group(1)
        # Months
        m_month = re.search(r'(\d+)\s*(?:month|months|شهر|أشهر)', ds)
        if m_month:
            return (today - timedelta(days=int(m_month.group(1)) * 30)).isoformat()
        # Weeks
        m_week = re.search(r'(\d+)\s*(?:w|week|weeks|أسبوع|أسابيع)', ds)
        if m_week:
            return (today - timedelta(days=int(m_week.group(1)) * 7)).isoformat()
        # Days
        m_day = re.search(r'(\d+)\s*(?:d|day|days|يوم|أيام)', ds)
        if m_day:
            return (today - timedelta(days=int(m_day.group(1)))).isoformat()
        # Hours / minutes / today / yesterday
        if any(w in ds for w in ['yesterday', 'أمس', 'امس']):
            return (today - timedelta(days=1)).isoformat()
        if any(w in ds for w in ['today', 'hour', 'ساعة', 'دقيقة', 'minute', 'just now', 'اليوم']):
            return today.isoformat()
    except Exception:
        pass
    return today.isoformat()


def normalize_job_dict(raw_job: dict, default_site: str = "") -> dict:
    """
    Takes any raw job dictionary and standardizes all fields into a unified schema.
    """
    title = str(raw_job.get("title") or "").strip()
    desc = str(raw_job.get("description") or "").strip()
    company = normalize_company(raw_job.get("company", ""), desc)
    location = str(raw_job.get("location") or "Not specified").strip()
    job_url = str(raw_job.get("job_url") or "").strip()

    is_scholarship = (
        raw_job.get("is_scholarship") is True
        or str(raw_job.get("is_scholarship")).lower() in ("true", "1")
        or str(raw_job.get("job_type", "")).lower() == "scholarship"
        or any(k in f"{title} {desc}".lower() for k in ["scholarship", "fellowship", "منحة"])
    )

    job_type = normalize_job_type(
        raw_job.get("job_type", "Not specified"),
        title=title,
        desc=desc,
        is_scholarship=is_scholarship
    )

    is_remote = normalize_is_remote(
        location=location,
        title=title,
        desc=desc,
        job_type=job_type,
        raw_is_remote=raw_job.get("is_remote", False)
    )

    date_posted = parse_job_date(raw_job.get("date_posted"))
    site = str(raw_job.get("site") or default_site or "").strip().lower()
    job_id = raw_job.get("job_id") or make_job_id(title, company, job_url)
    status = raw_job.get("status", "pending")
    is_applied = int(raw_job.get("is_applied", 0))

    norm = {
        "job_id": job_id,
        "title": title,
        "company": company,
        "location": location,
        "job_url": job_url,
        "job_type": job_type,
        "date_posted": date_posted,
        "site": site,
        "description": desc,
        "is_remote": is_remote,
        "is_scholarship": is_scholarship,
        "status": status,
        "is_applied": is_applied,
    }
    if "career_level" in raw_job and raw_job["career_level"]:
        norm["career_level"] = str(raw_job["career_level"]).strip()
    return norm


def score_job_dict(job_dict: dict, config: dict = None) -> dict:
    """
    Applies scoring to a normalized job dictionary, computing base_score and relevance_score.
    """
    from core.scorer import calculate_score, load_latest_config
    if config is None:
        config = load_latest_config()
    job_dict["base_score"] = calculate_score(job_dict, config=config, apply_date_penalty=False)
    job_dict["relevance_score"] = calculate_score(job_dict, config=config, apply_date_penalty=True)
    return job_dict


def process_scraped_batch(df_list: list, config: dict = None) -> Optional[pd.DataFrame]:
    """
    Cleans, normalizes, scores, and saves a batch of scraped DataFrames.
    - Dropped records (failing preliminary Stage 1 & 2): saved via save_dropped_jobs with minimal links.
    - Valid records (passing Stage 1 & 2): scored with date penalty, deduplicated, and saved via save_job.
    """
    if not df_list:
        return None
    cleaned = [df.dropna(axis=1, how='all') for df in df_list if df is not None and not df.empty]
    if not cleaned:
        return None
    batch_df = pd.concat(cleaned, ignore_index=True)
    batch_df = batch_df.drop_duplicates(subset=["job_url"])

    from core.scorer import load_latest_config
    from core.database import save_job, save_dropped_jobs, get_jobs_by_status
    import logging

    config = config or load_latest_config()
    records = batch_df.to_dict('records')
    normalized_records = [normalize_job_dict(r) for r in records]

    dropped_records = []
    valid_records = []

    for r in normalized_records:
        score_job_dict(r, config=config)
        is_schol = r.get('job_type') == 'Scholarship' or r.get('is_scholarship') is True
        if r.get('base_score', 0) > 0 or is_schol:
            valid_records.append(r)
        else:
            dropped_records.append(r)

    if dropped_records:
        save_dropped_jobs(dropped_records)
        logging.info(f"Filtered {len(dropped_records)} non-matching job(s) from preliminary stages (links recorded to avoid re-scraping).")

    if not valid_records:
        return None

    applied_or_rejected = get_jobs_by_status(['applied', 'not_related'])
    exclude_ids = {j['job_id'] for j in applied_or_rejected}
    valid_records = [r for r in valid_records if r['job_id'] not in exclude_ids]

    if not valid_records:
        return None

    saved_count = 0
    for r in valid_records:
        save_job(r)
        saved_count += 1

    logging.info(f"💾 Incrementally saved {saved_count} job(s) to SQLite database.")
    return pd.DataFrame(valid_records)
