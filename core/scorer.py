import logging
import sqlite3
import os
import json
import re
import time
import unicodedata
from datetime import date, datetime
from core.database import DB_PATH

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
    desc = str(row.get('description', '')).lower()
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
    search_terms = []
    arabic_search_terms = []
    for role in roles:
        search_terms.extend(role.get("english_terms", []))
        arabic_search_terms.extend(role.get("arabic_terms", []))
    if not search_terms:
        search_terms = config.get("SEARCH_TERMS", [])
    if not arabic_search_terms:
        arabic_search_terms = config.get("ARABIC_SEARCH_TERMS", [])

    resume_keywords = config.get("RESUME_KEYWORDS", [])
    exclude_keywords = config.get("EXCLUDE_KEYWORDS", [])
    excluded_companies = [c.lower() for c in config.get("EXCLUDED_COMPANIES", [])]
    favorite_companies = [c.lower() for c in config.get("FAVORITE_COMPANIES", [])]
    target_locations = [l.lower() for l in config.get("TARGET_LOCATIONS", ["cairo", "giza", "maadi", "nasr city", "new cairo"])]
    target_levels = [l.lower() for l in config.get("TARGET_LEVELS", ["junior", "fresh", "student", "intern", "entry"])]
    restricted_remote_keywords = [k.lower() for k in config.get("RESTRICTED_REMOTE_KEYWORDS", ['us only', 'uk only', 'eu only', 'united states', 'us applicants', 'us citizen', 'us citizenship'])]
    global_remote_keywords = [k.lower() for k in config.get("GLOBAL_REMOTE_KEYWORDS", ['africa', 'middle east', 'mena', 'worldwide', 'global'])]

    score = 0

    # 1. Negative Filtering: Excluded Companies
    if any(comp in company for comp in excluded_companies):
        return -100

    # 2. Negative Filtering: Excluded Keywords
    for kw in exclude_keywords:
        if not kw:
            continue
        pat = re.compile(r'\b' + re.escape(kw) + r'\b', re.IGNORECASE)
        if pat.search(title):
            score -= 50
        elif pat.search(job_type_val) or pat.search(career_level_val):
            score -= 40
        elif pat.search(desc):
            score -= 15

    # 3. Positive Matching: Search Terms / Roles
    has_term_match = False
    for term in search_terms:
        term_lower = term.lower()
        if term_lower in title:
            score += 20
            has_term_match = True
            break
        elif term_lower in desc:
            score += 5
            has_term_match = True
            break

    raw_title = str(row.get('title', ''))
    raw_desc = str(row.get('description', ''))
    for term in arabic_search_terms:
        if term in raw_title:
            score += 20
            has_term_match = True
            break
        elif term in raw_desc:
            score += 5
            has_term_match = True
            break

    is_scholarship = (
        job_type_val == 'scholarship'
        or row.get('is_scholarship') is True
        or str(row.get('is_scholarship')).lower() == 'true'
        or any(k in f"{title} {job_type_val}" for k in ['scholarship', 'fellowship', 'منحة'])
    )

    # 4. Positive Matching: Resume Skills (Awarded strictly once per unique keyword)
    matched_skills = 0
    for kw in resume_keywords:
        if not kw:
            continue
        pat = re.compile(r'\b' + re.escape(kw) + r'\b', re.IGNORECASE)
        if pat.search(title):
            score += 8
            matched_skills += 1
        elif pat.search(desc):
            score += 3
            matched_skills += 1

    # Zero baseline: If a job matches fewer than MIN_MATCHED_SKILLS (default 2) resume skills, it is unrelated (score = 0)
    min_skills = config.get("MIN_MATCHED_SKILLS", 2)
    if matched_skills < min_skills:
        if not is_scholarship:
            return 0


    # 5. Experience Penalty (Smooth Relative formula)
    user_exp = 1
    for role in roles:
        role_terms = [t.lower() for t in role.get('english_terms', [])] + [t.lower() for t in role.get('arabic_terms', [])]
        if any(term in title for term in role_terms):
            user_exp = role.get('years_experience', role.get('max_years_experience', 1))
            break

    extracted_exp = []
    text_to_check = f"{desc} {career_level_val} {title}"
    for min_y, _ in re.findall(r'\b(\d+)\s*(?:-|–|\s+to\s+)\s*(\d+)\s*(?:years?|yrs?)', text_to_check):
        try: extracted_exp.append(int(min_y))
        except ValueError: pass
    for y in re.findall(r'\b(\d+)\+?\s*(?:years?|yrs?)\b', text_to_check):
        try: extracted_exp.append(int(y))
        except ValueError: pass
    for y in re.findall(r'\b(?:minimum|at\s+least|min\.?)\s*(\d+)\+?\s*(?:years?|yrs?)', text_to_check):
        try: extracted_exp.append(int(y))
        except ValueError: pass
    for min_y, _ in re.findall(r'خبرة\s*(?:من\s+)?(\d+)\s*(?:إلى|-|–)\s*(\d+)\s*(?:سنوات|سنين|سنة)', text_to_check):
        try: extracted_exp.append(int(min_y))
        except ValueError: pass
    for y1, y2 in re.findall(r'(?:خبرة\s*(?:لا\s*تقل\s*عن)?\s*(\d+)|(\d+)\s*(?:سنوات|سنين|سنة)\s*(?:من\s+)?خبرة)', text_to_check):
        y = y1 or y2
        if y:
            try: extracted_exp.append(int(y))
            except ValueError: pass

    extracted_exp = [x for x in extracted_exp if 1 <= x <= 15]
    if extracted_exp:
        min_req_exp = min(extracted_exp)
        diff = min_req_exp - user_exp
        if diff > 0:
            score -= diff * 30

    # 6. Target Level Boost (Checked on structured title/job_type/career_level only)
    level_scope = f"{title} {job_type_val} {career_level_val}"
    for lvl in target_levels:
        if not lvl:
            continue
        lvl_pat = re.compile(r'\b' + re.escape(lvl) + r'\b', re.IGNORECASE)
        if lvl_pat.search(level_scope):
            score += 15
            break

    # 7. Favorite Companies Boost
    if any(comp in company for comp in favorite_companies):
        score += 15

    # 8. Target Location & Remote Eligibility
    full_loc_desc = f"{loc_val} {title} {desc}"
    if any(r in full_loc_desc for r in restricted_remote_keywords):
        score -= 100

    normalized_loc = unicodedata.normalize('NFKD', loc_val).encode('ascii', 'ignore').decode('utf-8')
    matches_target_loc = any(target in loc_val or target in normalized_loc for target in target_locations)

    if matches_target_loc:
        score += 5

    if is_remote:
        score += 5
        if any(g in full_loc_desc for g in global_remote_keywords):
            score += 5

    # Location Gate: Job MUST be located in target locations (Egypt) OR be Remote.
    # Discard foreign in-person / on-site jobs (e.g., Melbourne, Madrid, Bordeaux, San Diego).
    # Exception: Scholarships are often international/study-abroad programs and bypass this local gate.
    if not is_scholarship and not matches_target_loc and not is_remote:
        return 0

    # Discard non-relevant jobs before applying date adjustments
    if score <= 0:
        return 0

    # If date penalty is disabled (e.g. for base relevance eligibility), return base score directly
    if not apply_date_penalty:
        return int(score)

    # 9. Dynamic Daily Date Penalty (Negative score according to date posted)
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

    # No artificial floor value applied: raw age-decayed score is returned
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
    
    cursor.execute("SELECT * FROM jobs")
    rows = cursor.fetchall()
    
    jobs_to_update = []
    jobs_to_delete = []
    
    for row in rows:
        job_dict = dict(row)
        job_id = job_dict['job_id']
        status = job_dict.get('status', 'pending')
        is_applied = job_dict.get('is_applied', 0)
        is_scholarship_job = (
            job_dict.get('job_type', '').lower() == 'scholarship'
            or str(job_dict.get('is_scholarship', '')).lower() in ('true', '1')
        )
        
        final_score = calculate_score(job_dict, config=config, apply_date_penalty=True)

        # Prune pending jobs that are not relevant (score <= 0 due to skills/location/exclusions or age decay)
        # Note: Liked jobs, Applied jobs, and Scholarships are protected from pruning
        if status == 'pending' and not is_scholarship_job and is_applied != 1:
            if final_score <= 0:
                jobs_to_delete.append((job_id,))
            else:
                jobs_to_update.append((final_score, job_id))
        else:
            jobs_to_update.append((final_score, job_id))
            
    if jobs_to_delete:
        cursor.executemany("DELETE FROM jobs WHERE job_id = ?", jobs_to_delete)
    if jobs_to_update:
        cursor.executemany("UPDATE jobs SET relevance_score = ? WHERE job_id = ?", jobs_to_update)
        
    conn.commit()
    conn.close()
    
    duration = round(time.time() - t0, 3)
    logging.info(f"Rescored {len(jobs_to_update)} jobs, pruned {len(jobs_to_delete)} jobs in {duration}s")
    return {
        "status": "success",
        "rescored": len(jobs_to_update),
        "removed": len(jobs_to_delete),
        "duration_seconds": duration
    }
