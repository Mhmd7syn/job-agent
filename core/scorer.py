import logging
import sqlite3
import os
import json
import re
import time
import unicodedata
from datetime import date, datetime
from core.database import DB_PATH
from core.career_levels import expand_levels, get_excluded_levels

SENIORITY_EXCLUDE_KEYWORDS = {
    "senior", "lead", "manager", "principal", "head", "director", "sr",
    "staff", "expert", "phd", "architect", "vp", "executive", "mid-level",
    "intermediate"
}

def load_latest_config():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, 'core', 'config.json')
    default_path = os.path.join(base_dir, 'core', 'config.default.json')
    
    target_path = config_path if os.path.exists(config_path) else default_path
    if not os.path.exists(target_path):
        return {}
    with open(target_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def calculate_score(row, config=None, apply_date_penalty=True):
    if config is None:
        config = load_latest_config()

    title = str(row.get('title', '')).lower()
    raw_title = str(row.get('title', ''))
    desc = str(row.get('description', '')).lower()
    raw_desc = str(row.get('description', ''))
    company = str(row.get('company', '')).lower()
    job_type_val = str(row.get('job_type', '')).lower()
    career_level_val = str(row.get('career_level', '')).lower() if 'career_level' in row else ''
    loc_val = str(row.get('location', '')).lower()
    is_remote_col = row.get('is_remote', False)
    is_remote = (
        is_remote_col is True 
        or str(is_remote_col).lower() == 'true' 
        or 'remote' in loc_val 
        or 'remote' in title 
        or 'remote' in job_type_val 
        or 'work from home' in loc_val 
        or 'work from home' in title
    )

    roles = config.get("ROLES", [])
    all_search_terms = []
    for role in roles:
        all_search_terms.extend(role.get("english_terms", role.get("terms", [])))
    if not all_search_terms:
        all_search_terms = config.get("SEARCH_TERMS", [])

    resume_keywords = config.get("RESUME_KEYWORDS", [])
    exclude_keywords = config.get("EXCLUDE_KEYWORDS", [])
    excluded_companies = [c.lower() for c in config.get("EXCLUDED_COMPANIES", []) if c.strip()]
    favorite_companies = [c.lower() for c in config.get("FAVORITE_COMPANIES", []) if c.strip()]
    target_locations = [l.lower() for l in config.get("TARGET_LOCATIONS", ["cairo", "giza", "maadi", "nasr city", "new cairo"])]
    target_levels_cfg = config.get("TARGET_LEVELS", ["Intern / Student", "Fresh Graduate / Entry-level", "Junior"])
    level_exclude_cfg = config.get("LEVEL_EXCLUDE", None)

    target_level_synonyms = expand_levels(target_levels_cfg)
    if level_exclude_cfg is not None:
        excluded_level_synonyms = expand_levels(level_exclude_cfg)
    else:
        excluded_categories = get_excluded_levels(target_levels_cfg)
        excluded_level_synonyms = expand_levels(excluded_categories)

    # Disregard any excluded synonym if it's already covered in target levels
    effective_excluded_synonyms = excluded_level_synonyms - target_level_synonyms

    restricted_remote_keywords = [k.lower() for k in config.get("RESTRICTED_REMOTE_KEYWORDS", ['us only', 'uk only', 'eu only', 'united states', 'us applicants', 'us citizen', 'us citizenship'])]

    # -------------------------------------------------------------
    # STAGE 1: Hard Disqualification Gate
    # -------------------------------------------------------------
    if any(comp in company for comp in excluded_companies):
        return 0

    full_loc_desc = f"{loc_val} {title} {desc}"
    if any(r in full_loc_desc for r in restricted_remote_keywords):
        return 0

    # Career Level Scope
    level_scope = f"{title} {job_type_val} {career_level_val}"
    # Guard against phrases like "non-manager" or "non manager" triggering false positive on "manager"
    clean_level_scope = re.sub(r'\bnon[-\s]manager\b', '', level_scope, flags=re.IGNORECASE)

    # Hard Disqualification: Seniority level in LEVEL_EXCLUDE
    for syn in effective_excluded_synonyms:
        if not syn:
            continue
        syn_pat = re.compile(r'\b' + re.escape(syn) + r'\b', re.IGNORECASE)
        if syn_pat.search(clean_level_scope):
            return 0

    # Excluded seniority or title keywords in Title / Career Level
    for kw in exclude_keywords:
        if not kw:
            continue
        kw_clean = kw.strip().lower()
        pat = re.compile(r'\b' + re.escape(kw_clean) + r'\b', re.IGNORECASE)
        if pat.search(title) or (kw_clean in SENIORITY_EXCLUDE_KEYWORDS and pat.search(clean_level_scope)):
            return 0

    is_scholarship = (
        job_type_val in ('scholarship', 'competition', 'hackathon')
        or row.get('is_scholarship') is True
        or str(row.get('is_scholarship')).lower() == 'true'
        or any(k in f"{title} {job_type_val}" for k in [
            'scholarship', 'fellowship', 'competition', 'hackathon'
        ])
    )

    # -------------------------------------------------------------
    # STAGE 2: Core Technical Relevance Gate
    # -------------------------------------------------------------
    tech_score = 0

    # Role terms in title (+20) or description (+5)
    role_matched = False
    for term in all_search_terms:
        if not term:
            continue
        term_clean = term.strip().lower()
        if term_clean in title:
            tech_score += 20
            role_matched = True
            break
    if not role_matched:
        for term in all_search_terms:
            if not term:
                continue
            term_clean = term.strip().lower()
            if term_clean in desc:
                tech_score += 5
                break

    # Technical Skills in title (+8) or description (+3)
    for kw in resume_keywords:
        if not kw:
            continue
        pat = re.compile(r'\b' + re.escape(kw) + r'\b', re.IGNORECASE)
        if pat.search(title):
            tech_score += 8
        elif pat.search(desc):
            tech_score += 3

    # SIMPLE GATE: If no technical match at all, STOP!
    # Non-tech roles (Accountants, HR, Sales) die here without receiving generic boosts.
    if tech_score == 0 and not is_scholarship:
        return 0

    score = tech_score

    # -------------------------------------------------------------
    # STAGE 3: Contextual Boosts (Only for Verified Technical Jobs)
    # -------------------------------------------------------------
    # Target Seniority Level Boost
    for lvl in target_level_synonyms:
        if not lvl:
            continue
        lvl_pat = re.compile(r'\b' + re.escape(lvl) + r'\b', re.IGNORECASE)
        if lvl_pat.search(clean_level_scope):
            score += 15
            break

    # Favorite Companies Boost
    if any(comp in company for comp in favorite_companies):
        score += 15

    # Location check: fair +5 for Target Location OR Remote
    normalized_loc = unicodedata.normalize('NFKD', loc_val).encode('ascii', 'ignore').decode('utf-8')
    matches_target_loc = any(target in loc_val or target in normalized_loc for target in target_locations)

    if matches_target_loc or is_remote:
        score += 5

    # Location Gate: Reject in-person jobs located outside target country (e.g. on-site Germany/UK)
    if not is_scholarship and not matches_target_loc and not is_remote:
        return 0

    # Domain Exclude Keywords in Description (e.g. Sales, Cold Calling)
    for kw in exclude_keywords:
        if not kw:
            continue
        kw_clean = kw.strip().lower()
        if kw_clean not in SENIORITY_EXCLUDE_KEYWORDS:
            pat = re.compile(r'\b' + re.escape(kw_clean) + r'\b', re.IGNORECASE)
            if pat.search(desc):
                score -= 15

    # Experience Penalty (5 points per year gap)
    user_exp = 0
    for role in roles:
        role_terms = [t.lower() for t in role.get('english_terms', role.get('terms', []))]
        if any(term in title for term in role_terms):
            user_exp = role.get('years_experience', 0)
            break

    extracted_exp = []
    text_to_check = f"{desc}\n{career_level_val}\n{title}"
    sentences = re.split(r'[\n\.\;\•\*\!\?]+', text_to_check)

    company_indicators = [
        'about us', 'who we are', 'our company', 'the company', 'we are', 'we have been',
        'founded', 'established', 'in the market', 'our team', 'our organization',
        'serving clients', 'industry leader', 'history of', 'track record of'
    ]
    req_indicators = [
        'required', 'requirement', 'requirements', 'must', 'minimum', 'at least',
        'looking for', 'seeking', 'candidate', 'applicant', 'qualification', 'qualifications',
        'should have', 'plus', 'preferred'
    ]

    for sentence in sentences:
        s_clean = sentence.strip()
        s_lower = s_clean.lower()
        if not s_clean:
            continue
        if any(kw in s_lower for kw in ['experience', 'exp']):
            # Filter out company background descriptions that lack candidate requirement cues
            if any(ci in s_lower for ci in company_indicators) and not any(ri in s_lower for ri in req_indicators):
                continue

            # Strip leading list numbers like "1.", "2)", "- "
            s_clean_text = re.sub(r'^\s*\d+[\.\)\-]\s*', '', s_clean)

            # Extract numbers from the sentence (< 40 to avoid calendar years like 2024 or phone numbers)
            # min(nums) naturally handles both single numbers (e.g. [2] -> 2) and ranges (e.g. [0, 2] -> 0)
            nums = [int(n) for n in re.findall(r'\b\d+\b', s_clean_text) if int(n) < 40]
            if nums:
                extracted_exp.append(min(nums))

    if extracted_exp:
        min_req_exp = min(extracted_exp)
        diff = min_req_exp - user_exp
        if diff > 0:
            score -= diff * 5

    # If date penalty is disabled, return base score directly
    if not apply_date_penalty:
        return int(score)

    # -------------------------------------------------------------
    # STAGE 4: Recency / Daily Date Penalty
    # -------------------------------------------------------------
    post_date_raw = row.get('date_posted')
    if post_date_raw:
        try:
            if hasattr(post_date_raw, 'date'):
                p_date = post_date_raw.date()
            elif isinstance(post_date_raw, date):
                p_date = post_date_raw
            else:
                p_date = datetime.strptime(str(post_date_raw).strip()[:10], "%Y-%m-%d").date()
            days_old = max(0, (date.today() - p_date).days)
            daily_penalty = config.get("DAILY_DATE_PENALTY", 1.5) if config else 1.5
            max_penalty = config.get("MAX_DATE_PENALTY", 30) if config else 30
            penalty = min(max_penalty, days_old * daily_penalty)
            score -= penalty
        except Exception as e:
            logging.debug(f"Date parsing failed for '{post_date_raw}': {e}")

    # Raw score returned without artificial floor; score <= 0 simply ranks at the bottom
    return int(score)

def is_valid_job(row, base_score=None, config=None):
    """A job is valid if its base career criteria relevance score is greater than zero."""
    if base_score is not None:
        return base_score > 0
    return calculate_score(row, config=config, apply_date_penalty=False) > 0

def rescore_all_jobs():
    t0 = time.time()
    config = load_latest_config()

    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM jobs WHERE status IN ('pending', 'liked', 'not_related')")
    rows = cursor.fetchall()
    
    jobs_to_update = []
    
    for row in rows:
        job_dict = dict(row)
        job_id = job_dict['job_id']
        final_score = calculate_score(job_dict, config=config, apply_date_penalty=True)
        jobs_to_update.append((final_score, job_id))
            
    if jobs_to_update:
        cursor.executemany("UPDATE jobs SET relevance_score = ? WHERE job_id = ?", jobs_to_update)
        
    conn.commit()
    conn.close()
    
    duration = round(time.time() - t0, 3)
    logging.info(f"Rescored {len(jobs_to_update)} jobs in {duration}s")
    return {
        "status": "success",
        "rescored": len(jobs_to_update),
        "removed": 0,
        "duration_seconds": duration
    }
