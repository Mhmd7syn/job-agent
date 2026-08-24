import logging
import sqlite3
import os
import json
import re
import time
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

def calculate_score(row, config=None):
    if config is None:
        config = load_latest_config()

    title = str(row.get('title', '')).lower()
    desc = str(row.get('description', '')).lower()
    company = str(row.get('company', '')).lower()
    job_type_val = str(row.get('job_type', '')).lower()
    career_level_val = str(row.get('career_level', '')).lower() if 'career_level' in row else ''
    loc_val = str(row.get('location', '')).lower()
    is_remote_col = row.get('is_remote', False)
    is_remote = (is_remote_col is True or str(is_remote_col).lower() == 'true' or 'remote' in loc_val or 'remote' in title)

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
    if any(target in loc_val for target in target_locations):
        score += 5

    if is_remote:
        score += 5
        full_loc_desc = f"{loc_val} {title} {desc}"
        if any(r in full_loc_desc for r in restricted_remote_keywords):
            score -= 100
        elif any(g in full_loc_desc for g in global_remote_keywords):
            score += 5

    # 9. Dynamic Daily Freshness Decay Boost (New jobs have priority, updated daily)
    post_date_raw = row.get('date_posted')
    if post_date_raw:
        try:
            if hasattr(post_date_raw, 'date'):
                p_date = post_date_raw.date()
            else:
                p_date = datetime.strptime(str(post_date_raw)[:10], "%Y-%m-%d").date()
            days_old = (date.today() - p_date).days
            if days_old >= 0:
                freshness_boost = max(0, 15 - days_old)
                if freshness_boost > 0:
                    score += freshness_boost
        except Exception as e:
            logging.debug(f"Date parsing failed for '{post_date_raw}': {e}")

    return int(score)

def is_valid_job(row, score):
    """A job is valid if its final relevance score is greater than zero."""
    return score > 0

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
        new_score = calculate_score(job_dict, config=config)
        job_id = job_dict['job_id']
        status = job_dict.get('status', 'pending')
        
        # Prune pending jobs that are not relevant (score <= 0)
        if status == 'pending' and not is_valid_job(job_dict, new_score):
            jobs_to_delete.append((job_id,))
        else:
            jobs_to_update.append((new_score, job_id))
            
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
