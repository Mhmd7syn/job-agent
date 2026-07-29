import sqlite3
import os
import json
import re
import time
from datetime import datetime, date
import pandas as pd
from core.database import DB_PATH, get_liked_jobs

def load_latest_config():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, 'core', 'config.json')
    default_path = os.path.join(base_dir, 'core', 'config.default.json')
    
    target_path = config_path if os.path.exists(config_path) else default_path
    if not os.path.exists(target_path):
        return {}
    with open(target_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def rescore_all_jobs():
    t0 = time.time()
    config = load_latest_config()
    
    # Extract config parameters
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
    nice_to_have_skills = config.get("NICE_TO_HAVE_SKILLS", [])
    exclude_keywords = config.get("EXCLUDE_KEYWORDS", [])
    excluded_companies = [c.lower() for c in config.get("EXCLUDED_COMPANIES", [])]
    favorite_companies = [c.lower() for c in config.get("FAVORITE_COMPANIES", [])]
    
    location_rules = [l.lower() for l in config.get("LOCATION", ["Egypt"])]
    target_locations = [l.lower() for l in config.get("TARGET_LOCATIONS", ["cairo", "giza", "maadi", "nasr city", "new cairo"])]
    target_levels = [l.lower() for l in config.get("TARGET_LEVELS", ["junior", "fresh", "student", "intern", "entry"])]
    hours_old_max = config.get("HOURS_OLD", 168)
    
    global_remote_keywords = [k.lower() for k in config.get("GLOBAL_REMOTE_KEYWORDS", ['africa', 'middle east', 'mena', 'worldwide', 'global'])]
    restricted_remote_keywords = [k.lower() for k in config.get("RESTRICTED_REMOTE_KEYWORDS", ['us only', 'uk only', 'eu only'])]

    # Precompile regex patterns for performance
    exclude_patterns = [re.compile(r'\b' + re.escape(kw) + r'\b', re.IGNORECASE) for kw in exclude_keywords if kw]
    resume_patterns = [re.compile(r'\b' + re.escape(kw) + r'\b', re.IGNORECASE) for kw in resume_keywords if kw]
    nice_patterns = [re.compile(r'\b' + re.escape(kw) + r'\b', re.IGNORECASE) for kw in nice_to_have_skills if kw]

    # Liked jobs feedback loop
    liked_jobs = get_liked_jobs()
    liked_companies = {str(j['company']).lower() for j in liked_jobs if j.get('company')}
    liked_titles_words = set()
    for j in liked_jobs:
        if j.get('title'):
            for word in re.findall(r'\b\w+\b', str(j['title']).lower()):
                if len(word) > 3:
                    liked_titles_words.add(word)

    # Helper filters
    allow_remote = any('remote' in loc_item for loc_item in location_rules)
    title_keywords = {t.lower() for t in search_terms} | {
        'data', 'ai', 'machine learning', 'python', 'analyst', 'engineer',
        'instructor', 'trainer', 'computer vision', 'nlp', 'scientist', 'ml',
        'deep learning', 'analytics', 'intelligence', 'developer'
    } | {t for t in arabic_search_terms}

    def calculate_score(row):
        title = str(row.get('title', '')).lower()
        desc = str(row.get('description', '')).lower()
        company = str(row.get('company', '')).lower()
        job_type_val = str(row.get('job_type', '')).lower()
        
        # 0. Smart Feedback Loop (Boost from previously Liked Jobs)
        score = 0
        if company and company in liked_companies:
            score += 20
        title_words = set(re.findall(r'\b\w+\b', title))
        shared_words = title_words.intersection(liked_titles_words)
        if shared_words:
            score += len(shared_words) * 3

        # 1. Negative Filtering
        career_level_val = str(row.get('career_level', '')).lower() if 'career_level' in row else ''
        for pattern in exclude_patterns:
            if pattern.search(title):
                score -= 50
            elif pattern.search(job_type_val) or pattern.search(career_level_val):
                score -= 40
            elif pattern.search(desc):
                score -= 10

        # Instant drop for spammy companies
        if any(comp in company for comp in excluded_companies):
            return -100

        # 2. Company Whitelist Boost
        if any(comp in company for comp in favorite_companies):
            score += 15

        for term in search_terms:
            term_lower = term.lower()
            if term_lower in title:
                score += 10
            elif term_lower in desc:
                score += 3

        raw_title = str(row.get('title', ''))
        raw_desc = str(row.get('description', ''))
        for term in arabic_search_terms:
            if term in raw_title:
                score += 10
            elif term in raw_desc:
                score += 3

        # Match Role-specific Rules & Experience Check
        max_exp_allowed = 3
        for role in roles:
            role_terms = [t.lower() for t in role.get('english_terms', [])] + [t.lower() for t in role.get('arabic_terms', [])]
            if any(term in title for term in role_terms):
                max_exp_allowed = role.get('max_years_experience', 3)
                break
        
        exp_match = re.search(r'(\d+)(?:\+|-)?\s*years?(?:\s+of)?\s+experience', desc)
        if not exp_match:
            exp_match = re.search(r'experience.*?:.*?(?<!\w)(\d+)\+?', desc)
        if exp_match:
            try:
                years = int(exp_match.group(1))
                if years > max_exp_allowed:
                    score -= 50
            except:
                pass

        # 3. Resume Match Scoring
        for pattern in resume_patterns:
            if pattern.search(title):
                score += 5
            matches = len(pattern.findall(desc))
            if matches > 0:
                score += min(matches * 2, 8)

        # 4. Nice-to-Have Skills
        for pattern in nice_patterns:
            if pattern.search(title):
                score += 3
            matches = len(pattern.findall(desc))
            if matches > 0:
                score += min(matches * 1, 3)

        # Score locations
        loc_val = str(row.get('location', '')).lower()
        is_remote_col = row.get('is_remote', False)
        if allow_remote and ((is_remote_col is True or str(is_remote_col).lower() == 'true') or ('remote' in loc_val) or ('remote' in title)):
            score += 5
            title_desc = title + " " + desc
            if any(r in title_desc for r in global_remote_keywords):
                score += 5
            if any(r in title_desc for r in restricted_remote_keywords):
                score -= 30

        if any(target in loc_val for target in target_locations):
            score += 5

        # Score levels
        if any(level in title or level in job_type_val or level in desc for level in target_levels):
            score += 15

        # Recency Boost (Never penalize older jobs, only boost fresh ones)
        post_date = row.get('date_posted')
        if pd.notna(post_date) and str(post_date).strip():
            try:
                if hasattr(post_date, 'date'):
                    p_date = post_date.date()
                else:
                    p_date = pd.to_datetime(post_date).date()
                days_old = (date.today() - p_date).days
                if hours_old_max > 0 and days_old * 24 <= hours_old_max:
                    hours_old_calc = days_old * 24
                    freshness_ratio = max(0.0, 1.0 - (hours_old_calc / hours_old_max))
                    score += int(15 * freshness_ratio)
            except Exception:
                pass

        return score

    def is_valid_job(row, score):
        if score <= 0:
            return False
        loc_val = str(row.get('location', '')).lower()
        is_remote = row.get('is_remote', False)
        geo_ok = False
        if is_remote is True or str(is_remote).lower() == 'true' or 'remote' in loc_val:
            geo_ok = True
        elif any(t in loc_val for t in target_locations) or 'egypt' in loc_val:
            geo_ok = True
        elif loc_val in ('', 'nan', 'not specified', 'unknown', 'none'):
            geo_ok = True
        if not geo_ok:
            return False
            
        title = str(row.get('title', '')).lower()
        if not any(kw in title for kw in title_keywords):
            return False
        return True

    # Process database records
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM jobs")
    rows = cursor.fetchall()
    
    jobs_to_update = []
    jobs_to_delete = []
    
    for row in rows:
        job_dict = dict(row)
        new_score = calculate_score(job_dict)
        job_id = job_dict['job_id']
        status = job_dict.get('status', 'pending')
        
        # We only prune/remove jobs that are still 'pending' and no longer valid or have score <= 0
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
    return {
        "status": "success",
        "rescored": len(jobs_to_update),
        "removed": len(jobs_to_delete),
        "duration_seconds": duration
    }
