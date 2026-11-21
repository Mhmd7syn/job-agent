import logging
import sqlite3
import os
import json
import re
import time
import unicodedata
from typing import Optional, List, Tuple, Dict, Set
from functools import lru_cache
from datetime import date, datetime
from core.database import DB_PATH
from core.career_levels import expand_levels, get_excluded_levels

from core.text_normalizer import (
    get_word_pattern as _get_word_pattern,
    normalize_text,
    normalize_phrase,
    PROTECTED_ACRONYMS
)
from core.skill_ontology import ontology
from core.role_keywords import get_resume_keywords_for_role, get_unified_resume_keywords

SENIORITY_EXCLUDE_KEYWORDS = {
    "senior", "lead", "manager", "principal", "head", "director", "sr",
    "staff", "expert", "phd", "architect", "vp", "executive", "mid-level",
    "intermediate"
}

COMPANY_INDICATORS = (
    'about us', 'who we are', 'our company', 'the company', 'we are', 'we have been',
    'founded', 'established', 'in the market', 'our team', 'our organization',
    'serving clients', 'industry leader', 'history of', 'track record of'
)

REQUIREMENT_INDICATORS = (
    'required', 'requirement', 'requirements', 'must', 'minimum', 'at least',
    'looking for', 'seeking', 'candidate', 'applicant', 'qualification', 'qualifications',
    'should have', 'plus', 'preferred'
)

# Legacy alias for backward compatibility
SKILL_CANONICAL_MAP = {
    "ml": "machine learning",
    "dl": "deep learning",
    "nlp": "natural language processing",
    "bi": "business intelligence",
    "eda": "exploratory data analysis",
    "api": "rest api",
    "restful api": "rest api",
    "data analytics": "data analysis",
    "data analyst": "data analysis",
    "statistics": "statistical analysis",
    "teaching": "teacher",
    "mentoring": "mentor",
    "3d cnn": "cnn",
}

@lru_cache(maxsize=256)
def _get_term_parts_patterns(term: str):
    parts = term.split()
    if len(parts) >= 2:
        return re.compile(r'\b' + re.escape(parts[0]) + r'\b'), re.compile(r'\b' + re.escape(parts[-1]) + r'\b')
    return None

def matches_role_title(search_term: str, title: str, title_clean: Optional[str] = None) -> bool:
    """
    Matches role search terms in job titles.
    Supports exact phrases and compound/slash roles (e.g. 'ai engineer' matching 'AI/ML Engineer').
    """
    search_term = search_term.strip().lower()
    title_lower = title.lower()

    # 1. Exact phrase match
    if search_term in title_lower:
        return True
    if title_clean is None:
        title_clean = re.sub(r'[/\\_&,|-]', ' ', title_lower)
    if search_term in title_clean:
        return True

    # 2. Compound / slash role match (e.g. 'ai engineer' in 'AI/ML Engineer', 'data analyst' in 'Data & BI Analyst')
    pats = _get_term_parts_patterns(search_term)
    if pats:
        p_first, p_last = pats
        m_first = p_first.search(title_clean)
        if m_first:
            m_last = p_last.search(title_clean)
            if m_last and m_first.start() < m_last.start():
                intervening = title_clean[m_first.end():m_last.start()].split()
                if len(intervening) <= 4:
                    return True
    return False

def _build_compiled_kw_list(raw_kws: List[str]) -> list:
    """Precompiles regex pairs and ontology metadata for a keyword list."""
    seen_canonical = set()
    compiled = []
    sorted_kws = sorted(raw_kws, key=lambda k: len(k) if k else 0, reverse=True)
    for kw in sorted_kws:
        if not kw:
            continue
        kw_clean = kw.strip().lower()
        canon = ontology.get_canonical_skill(kw_clean)
        if canon in seen_canonical:
            continue
        seen_canonical.add(canon)
        pairs = ontology.get_synonym_pattern_pairs(kw_clean)
        lemma_pairs = ontology.get_lemma_pattern_pairs(kw_clean)
        is_acronym = len(kw_clean) <= 2 or kw_clean in PROTECTED_ACRONYMS
        compiled.append((kw_clean, canon, pairs, lemma_pairs, is_acronym))
    return compiled

def compile_scorer_meta(config: dict) -> dict:
    """
    Precompiles regexes, canonical maps, and role keywords for high-throughput batch scoring.
    Used by rescore_all_jobs to process thousands of jobs in milliseconds.
    """
    target_levels_cfg = config.get("TARGET_LEVELS", ["Intern / Student", "Fresh Graduate / Entry-level", "Junior"])
    level_exclude_cfg = config.get("LEVEL_EXCLUDE", None)
    target_level_synonyms = expand_levels(target_levels_cfg)
    if level_exclude_cfg is not None:
        excluded_level_synonyms = expand_levels(level_exclude_cfg)
    else:
        excluded_categories = get_excluded_levels(target_levels_cfg)
        excluded_level_synonyms = expand_levels(excluded_categories)
    effective_excluded_synonyms = excluded_level_synonyms - target_level_synonyms

    roles = config.get("ROLES", [])
    role_kws_map = {}
    role_compiled_kws = {}
    for r in roles:
        r_title = r.get("title", "")
        raw = get_resume_keywords_for_role(r_title, config=config)
        role_kws_map[r_title] = raw
        role_compiled_kws[r_title] = _build_compiled_kw_list(raw)

    unified_raw = get_unified_resume_keywords(config=config)
    unified_compiled = _build_compiled_kw_list(unified_raw)

    excluded_companies = [(c.lower(), _get_word_pattern(c.lower())) for c in config.get("EXCLUDED_COMPANIES", []) if c.strip()]
    favorite_companies = [(c.lower(), _get_word_pattern(c.lower())) for c in config.get("FAVORITE_COMPANIES", []) if c.strip()]
    exclude_keywords = [(k.strip().lower(), _get_word_pattern(k.strip().lower())) for k in config.get("EXCLUDE_KEYWORDS", []) if k.strip()]
    target_locations = [l.lower() for l in config.get("TARGET_LOCATIONS", ["cairo", "giza", "maadi", "nasr city", "new cairo"])]
    restricted_remote = [k.lower() for k in config.get("RESTRICTED_REMOTE_KEYWORDS", ['us only', 'uk only', 'eu only', 'united states', 'us applicants', 'us citizen', 'us citizenship'])]
    effective_excluded_syns_pats = [(s, _get_word_pattern(s)) for s in effective_excluded_synonyms if s]
    target_level_pats = [(s, _get_word_pattern(s)) for s in target_level_synonyms if s]

    return {
        "target_level_synonyms": target_level_synonyms,
        "effective_excluded_synonyms": effective_excluded_synonyms,
        "effective_excluded_syns_pats": effective_excluded_syns_pats,
        "target_level_pats": target_level_pats,
        "excluded_companies": excluded_companies,
        "favorite_companies": favorite_companies,
        "exclude_keywords": exclude_keywords,
        "target_locations": target_locations,
        "restricted_remote": restricted_remote,
        "role_kws_map": role_kws_map,
        "role_compiled_kws": role_compiled_kws,
        "unified_kws": unified_raw,
        "unified_compiled": unified_compiled,
    }

_RE_DEGREE_DURATION = re.compile(r'\b(?:bachelor|master|phd|degree)[^.\n\r;]{0,50}?\(\s*\d+\s*(?:years?|yrs?)\s*\)', re.IGNORECASE)
_RE_SENTENCE_SPLIT = re.compile(r'[\n\.\;\•\*\!\?]+')
_RE_EXP_YEARS_RANGE = re.compile(r'\b(\d+)(?:\s*(?:to|-)\s*(\d+))?\s*(?:\+)?\s*(?:years?|yrs?)\b', re.IGNORECASE)
_RE_EXP_MONTHS = re.compile(r'\b\d+\s*(?:months?|mos?|weeks?|days?)\b', re.IGNORECASE)
_RE_EXP_YEARS = re.compile(r'\b\d+\s*(?:years?|yrs?)\b', re.IGNORECASE)
_RE_LEADING_DIGIT = re.compile(r'^\s*\d+[\.\)]\s*')

def extract_experience_years(text: str) -> Optional[int]:
    """
    Extracts the minimum required years of experience from job text.
    Handles single numbers, ranges, degree duration exclusions, and company history filters.
    Strictly requires year units (years/yrs) to avoid false penalties from '6 months', 'Python 3', etc.
    """
    if not text or ('experience' not in text and 'exp' not in text):
        return None

    cleaned = _RE_DEGREE_DURATION.sub('', text)

    extracted = []
    sentences = _RE_SENTENCE_SPLIT.split(cleaned)
    for s in sentences:
        s_clean = s.strip()
        s_lower = s_clean.lower()
        if not s_clean or not ('experience' in s_lower or 'exp' in s_lower):
            continue

        if any(ci in s_lower for ci in COMPANY_INDICATORS) and not any(ri in s_lower for ri in REQUIREMENT_INDICATORS):
            continue

        # Reject sentences specifying months/weeks rather than years
        if _RE_EXP_MONTHS.search(s_lower) and not _RE_EXP_YEARS.search(s_lower):
            continue

        s_clean_text = _RE_LEADING_DIGIT.sub('', s_clean)
        for m in _RE_EXP_YEARS_RANGE.finditer(s_clean_text):
            nums = [int(n) for n in m.groups() if n is not None and int(n) < 40]
            if nums:
                extracted.append(min(nums))

    return min(extracted) if extracted else None

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

    meta = config.get("_compiled_meta")
    if meta:
        target_level_synonyms = meta["target_level_synonyms"]
        effective_excluded_synonyms = meta["effective_excluded_synonyms"]
    else:
        target_level_synonyms = expand_levels(target_levels_cfg)
        if level_exclude_cfg is not None:
            excluded_level_synonyms = expand_levels(level_exclude_cfg)
        else:
            excluded_categories = get_excluded_levels(target_levels_cfg)
            excluded_level_synonyms = expand_levels(excluded_categories)
        effective_excluded_synonyms = excluded_level_synonyms - target_level_synonyms

    restricted_remote_keywords = [k.lower() for k in config.get("RESTRICTED_REMOTE_KEYWORDS", ['us only', 'uk only', 'eu only', 'united states', 'us applicants', 'us citizen', 'us citizenship'])]

    # -------------------------------------------------------------
    # STAGE 1: Hard Disqualification Gate
    # -------------------------------------------------------------
    if meta and "excluded_companies" in meta:
        for comp, pat in meta["excluded_companies"]:
            if comp in company and pat.search(company):
                return 0
    else:
        if any(comp and (comp in company) and _get_word_pattern(comp).search(company) for comp in excluded_companies):
            return 0

    full_loc_desc = f"{loc_val} {title} {desc}"
    restricted_remote = meta["restricted_remote"] if (meta and "restricted_remote" in meta) else restricted_remote_keywords
    if any(r in full_loc_desc for r in restricted_remote):
        return 0

    # Career Level Scope
    level_scope = f"{title} {job_type_val} {career_level_val}"
    # Guard against phrases like "non-manager" or "non manager" triggering false positive on "manager"
    clean_level_scope = re.sub(r'\bnon[-\s]manager\b', '', level_scope, flags=re.IGNORECASE)

    # Hard Disqualification: Seniority level in LEVEL_EXCLUDE
    if meta and "effective_excluded_syns_pats" in meta:
        for syn, pat in meta["effective_excluded_syns_pats"]:
            if syn in clean_level_scope and pat.search(clean_level_scope):
                return 0
    else:
        for syn in effective_excluded_synonyms:
            if syn and (syn in clean_level_scope) and _get_word_pattern(syn).search(clean_level_scope):
                return 0

    # Excluded seniority or title keywords in Title / Career Level
    if meta and "exclude_keywords" in meta:
        for kw_clean, pat in meta["exclude_keywords"]:
            if kw_clean in title or (kw_clean in SENIORITY_EXCLUDE_KEYWORDS and kw_clean in clean_level_scope):
                if pat.search(title) or (kw_clean in SENIORITY_EXCLUDE_KEYWORDS and pat.search(clean_level_scope)):
                    return 0
    else:
        for kw in exclude_keywords:
            if not kw:
                continue
            kw_clean = kw.strip().lower()
            if kw_clean in title or (kw_clean in SENIORITY_EXCLUDE_KEYWORDS and kw_clean in clean_level_scope):
                pat = _get_word_pattern(kw_clean)
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
    # STAGE 2: Core Technical Relevance Gate (Role-Scoped & Ontology-Powered)
    # -------------------------------------------------------------
    tech_score = 0

    # Match target roles in title (+20) or description (+5)
    role_matched = False
    matching_roles = []
    title_clean = None

    # 1. Match role terms in job title
    for role in roles:
        role_terms = role.get("english_terms", role.get("terms", []))
        for term in role_terms:
            if not term:
                continue
            if title_clean is None:
                title_clean = re.sub(r'[/\\_&,|-]', ' ', title)
            if matches_role_title(term, title, title_clean):
                matching_roles.append(role)
                role_matched = True
                break

    if role_matched:
        tech_score += 20
    else:
        # 2. Match role terms in description
        for role in roles:
            role_terms = role.get("english_terms", role.get("terms", []))
            if any(term and term.strip().lower() in desc for term in role_terms):
                matching_roles.append(role)
                role_matched = True
        if role_matched:
            tech_score += 5
        elif all_search_terms:
            # Fallback for plain SEARCH_TERMS when ROLES list is empty
            for term in all_search_terms:
                if not term:
                    continue
                if title_clean is None:
                    title_clean = re.sub(r'[/\\_&,|-]', ' ', title)
                if matches_role_title(term, title, title_clean):
                    tech_score += 20
                    role_matched = True
                    break
            if not role_matched:
                for term in all_search_terms:
                    if not term:
                        continue
                    if term.strip().lower() in desc:
                        tech_score += 5
                        role_matched = True
                        break

    # Determine role-scoped resume keywords
    compiled_kws = None
    if meta and "role_compiled_kws" in meta:
        if matching_roles:
            if len(matching_roles) == 1:
                compiled_kws = meta["role_compiled_kws"].get(matching_roles[0].get("title", ""), meta.get("unified_compiled", []))
            else:
                seen_canon = set()
                compiled_kws = []
                for r in matching_roles:
                    r_title = r.get("title", "")
                    for kw_item in meta["role_compiled_kws"].get(r_title, []):
                        if kw_item[1] not in seen_canon:
                            seen_canon.add(kw_item[1])
                            compiled_kws.append(kw_item)
        else:
            compiled_kws = meta.get("unified_compiled", [])
    else:
        active_keywords = []
        if matching_roles:
            seen_canonical = set()
            for r in matching_roles:
                r_title = r.get("title", "")
                r_kws = meta["role_kws_map"].get(r_title) if (meta and "role_kws_map" in meta) else None
                if r_kws is None:
                    r_kws = get_resume_keywords_for_role(r_title, config=config)
                for kw in r_kws:
                    canon = ontology.get_canonical_skill(kw)
                    if canon not in seen_canonical:
                        seen_canonical.add(canon)
                        active_keywords.append(kw)

        # Fallback to unified role keywords or global config keywords
        if not active_keywords:
            if roles:
                active_keywords = meta["unified_kws"] if (meta and "unified_kws" in meta) else get_unified_resume_keywords(config=config)
            if not active_keywords:
                active_keywords = resume_keywords

    # Technical Skills in title (+8) or description (+3, cluster-aware)
    max_title_points = config.get("MAX_TITLE_TECH_POINTS", 8) if config else 8
    max_desc_points = config.get("MAX_DESC_TECH_POINTS", 30) if config else 30
    max_cluster_points = config.get("MAX_CLUSTER_POINTS", 12) if config else 12
    title_tech_score = 0

    seen_canonical_skills = set()
    matched_title_skills = []
    matched_desc_skills = []
    lemma_title = None
    lemma_desc = None

    if compiled_kws is not None:
        for kw_clean, canonical_skill, pairs, lemma_pairs, is_acronym in compiled_kws:
            if canonical_skill in seen_canonical_skills:
                continue
            matched_in_title = False
            matched_in_desc = False

            for syn_str, pat in pairs:
                if (max_title_points is None or title_tech_score < max_title_points) and syn_str in title and pat.search(title):
                    matched_in_title = True
                    break
                if syn_str in desc and pat.search(desc):
                    matched_in_desc = True
                    break

            if not matched_in_title and not matched_in_desc and not is_acronym:
                if any(l_str in title or l_str in desc for l_str, _ in lemma_pairs):
                    if lemma_title is None:
                        lemma_title = normalize_phrase(title)
                    if lemma_desc is None:
                        lemma_desc = normalize_phrase(desc)

                    for lemma_str, pat_lemma in lemma_pairs:
                        if (max_title_points is None or title_tech_score < max_title_points) and lemma_str in lemma_title and pat_lemma.search(lemma_title):
                            matched_in_title = True
                            break
                        if lemma_str in lemma_desc and pat_lemma.search(lemma_desc):
                            matched_in_desc = True
                            break

            if matched_in_title:
                title_tech_score += 8
                seen_canonical_skills.add(canonical_skill)
                matched_title_skills.append(kw_clean)
            elif matched_in_desc:
                seen_canonical_skills.add(canonical_skill)
                matched_desc_skills.append(kw_clean)
    else:
        sorted_keywords = sorted(active_keywords, key=lambda k: len(k) if k else 0, reverse=True)
        for kw in sorted_keywords:
            if not kw:
                continue
            kw_clean = kw.strip().lower()
            canonical_skill = ontology.get_canonical_skill(kw_clean)
            if canonical_skill in seen_canonical_skills:
                continue

            pairs = ontology.get_synonym_pattern_pairs(kw_clean)
            matched_in_title = False
            matched_in_desc = False

            # 1. Fast substring pre-check followed by precompiled regex
            for syn_str, pat in pairs:
                if (max_title_points is None or title_tech_score < max_title_points) and syn_str in title and pat.search(title):
                    matched_in_title = True
                    break
                if syn_str in desc and pat.search(desc):
                    matched_in_desc = True
                    break

            # 2. Lemmatized match if exact did not match
            if not matched_in_title and not matched_in_desc and len(kw_clean) > 2 and kw_clean not in PROTECTED_ACRONYMS:
                lemma_pairs = ontology.get_lemma_pattern_pairs(kw_clean)
                if any(l_str in title or l_str in desc for l_str, _ in lemma_pairs):
                    if lemma_title is None:
                        lemma_title = normalize_phrase(title)
                    if lemma_desc is None:
                        lemma_desc = normalize_phrase(desc)

                    for lemma_str, pat_lemma in lemma_pairs:
                        if (max_title_points is None or title_tech_score < max_title_points) and lemma_str in lemma_title and pat_lemma.search(lemma_title):
                            matched_in_title = True
                            break
                        if lemma_str in lemma_desc and pat_lemma.search(lemma_desc):
                            matched_in_desc = True
                            break

            if matched_in_title:
                title_tech_score += 8
                seen_canonical_skills.add(canonical_skill)
                matched_title_skills.append(kw_clean)
            elif matched_in_desc:
                seen_canonical_skills.add(canonical_skill)
                matched_desc_skills.append(kw_clean)

    if max_title_points is not None:
        title_tech_score = min(max_title_points, title_tech_score)

    if matched_desc_skills:
        desc_tech_score, _ = ontology.calculate_cluster_score(
            matched_desc_skills,
            base_points_per_skill=3,
            max_cluster_points=max_cluster_points
        )
    else:
        desc_tech_score = 0

    if max_desc_points is not None:
        desc_tech_score = min(max_desc_points, desc_tech_score)

    tech_score += title_tech_score + desc_tech_score

    # SIMPLE GATE: If no technical match at all, STOP!
    # Non-tech roles (Accountants, HR, Sales) die here without receiving generic boosts.
    if tech_score == 0 and not is_scholarship:
        return 0

    score = tech_score

    # -------------------------------------------------------------
    # STAGE 3: Contextual Boosts (Only for Verified Technical Jobs)
    # -------------------------------------------------------------
    # Target Seniority Level Boost
    if meta and "target_level_pats" in meta:
        for lvl, pat in meta["target_level_pats"]:
            if lvl in clean_level_scope and pat.search(clean_level_scope):
                score += 15
                break
    else:
        for lvl in target_level_synonyms:
            if lvl and (lvl in clean_level_scope) and _get_word_pattern(lvl).search(clean_level_scope):
                score += 15
                break

    # Favorite Companies Boost (word-boundary matched to prevent substring false-positives like 'iti' matching 'Meriti' or 'British')
    if meta and "favorite_companies" in meta:
        if any(comp in company and pat.search(company) for comp, pat in meta["favorite_companies"]):
            score += 15
    else:
        if any(comp and (comp in company) and _get_word_pattern(comp).search(company) for comp in favorite_companies):
            score += 15

    # Location check: fair +5 for Target Location OR Remote
    normalized_loc = unicodedata.normalize('NFKD', loc_val).encode('ascii', 'ignore').decode('utf-8')
    loc_targets = meta["target_locations"] if (meta and "target_locations" in meta) else target_locations
    matches_target_loc = any(target in loc_val or target in normalized_loc for target in loc_targets)

    if matches_target_loc or is_remote:
        score += 5

    # Location Gate: Reject in-person jobs located outside target country (e.g. on-site Germany/UK)
    if not is_scholarship and not matches_target_loc and not is_remote:
        return 0

    # Domain Exclude Keywords in Description (e.g. Sales, Cold Calling)
    if meta and "exclude_keywords" in meta:
        for kw_clean, pat in meta["exclude_keywords"]:
            if kw_clean not in SENIORITY_EXCLUDE_KEYWORDS:
                if kw_clean in desc and pat.search(desc):
                    score -= 15
    else:
        for kw in exclude_keywords:
            if not kw:
                continue
            kw_clean = kw.strip().lower()
            if kw_clean not in SENIORITY_EXCLUDE_KEYWORDS:
                if (kw_clean in desc) and _get_word_pattern(kw_clean).search(desc):
                    score -= 15

    # Experience Penalty (5 points per year gap)
    user_exp = 0
    for role in roles:
        role_terms = [t.lower() for t in role.get('english_terms', role.get('terms', []))]
        if any(term in title for term in role_terms):
            user_exp = role.get('years_experience', 0)
            break

    min_req_exp = extract_experience_years(f"{desc}\n{career_level_val}\n{title}")
    if min_req_exp is not None:
        diff = min_req_exp - user_exp
        if diff > 0:
            score -= diff * 5

    # If date penalty is disabled, return base score directly
    if not apply_date_penalty:
        return int(score)

    # -------------------------------------------------------------
    # STAGE 4: Recency / Daily Date Penalty
    # -------------------------------------------------------------
    post_date_raw = row.get('date_posted') or row.get('timestamp')
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
    config["_compiled_meta"] = compile_scorer_meta(config)

    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT job_id, relevance_score, title, description, company, job_type, location, date_posted, timestamp 
        FROM jobs 
        WHERE status IN ('pending', 'liked', 'not_related')
    """)
    rows = cursor.fetchall()
    
    jobs_to_update = []
    
    for row in rows:
        job_dict = dict(row)
        job_id = job_dict['job_id']
        current_score = job_dict.get('relevance_score')
        final_score = calculate_score(job_dict, config=config, apply_date_penalty=True)
        if current_score is None or current_score != final_score:
            jobs_to_update.append((final_score, job_id))
            
    if jobs_to_update:
        cursor.executemany("UPDATE jobs SET relevance_score = ? WHERE job_id = ?", jobs_to_update)
        conn.commit()
        
    conn.close()
    
    duration = round(time.time() - t0, 3)
    logging.info(f"Rescored {len(rows)} jobs (updated {len(jobs_to_update)}) in {duration}s")
    return {
        "status": "success",
        "rescored": len(rows),
        "updated": len(jobs_to_update),
        "removed": 0,
        "duration_seconds": duration
    }
