import os
import re
import logging
from typing import Dict, List, Optional, Tuple, Set

from core.text_normalizer import normalize_text, get_word_pattern
from core.skill_ontology import ontology, DOMAIN_CLUSTERS
from core.cv_parser import extract_text_from_file

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Comprehensive master vocabulary of atomic technical skills
MASTER_SKILL_VOCABULARY: List[str] = [
    # Languages
    "python", "sql", "mysql", "postgresql", "nosql", "mongodb", "c++", "c#", "c",
    "java", "javascript", "typescript", "r", "scala", "bash", "shell", "html", "css",
    # Core Machine Learning & Data Science
    "machine learning", "deep learning", "scikit-learn", "xgboost", "random forest",
    "lightgbm", "pytorch", "tensorflow", "keras", "neural networks", "cnn", "3d cnn",
    "rnn", "lstm", "gru", "svm", "naive bayes", "decision trees", "gradient boosting",
    "supervised learning", "unsupervised learning", "predictive modeling", "classification",
    "regression", "clustering", "outlier detection", "feature engineering",
    # Computer Vision
    "computer vision", "opencv", "yolo", "object detection", "image segmentation",
    "semantic segmentation", "image processing", "mediapipe", "vit", "resnet", "u-net",
    "monai", "torchvision", "albumentations", "kinematics",
    # NLP & Generative AI
    "nlp", "natural language processing", "llm", "transformers", "hugging face",
    "nltk", "spacy", "bert", "genai", "generative ai", "rag", "langchain", "llamaindex",
    "tf-idf", "sequence modeling",
    # Data Analytics & BI
    "power bi", "tableau", "excel", "dax", "business intelligence", "pandas",
    "numpy", "scipy", "matplotlib", "seaborn", "eda", "exploratory data analysis",
    "data cleaning", "data preprocessing", "etl", "data visualization", "dashboards",
    "kpi", "reporting", "star schema", "data modeling", "relational databases",
    "statistical analysis", "statistics", "hypothesis testing", "a/b testing",
    # Web / APIs / MLOps / Cloud
    "docker", "kubernetes", "aws", "azure", "gcp", "git", "github", "linux",
    "fastapi", "flask", "django", "streamlit", "rest api", "mlflow", "tensorboard",
    "ci/cd", "airflow",
    # Teaching & STEM
    "instructor", "teacher", "trainer", "teaching", "mentoring", "mentor",
    "curriculum design", "curriculum development", "scratch", "mblock", "pictoblox",
    "stem", "robotics", "arduino"
]

import time

# Cache format: file_path -> (last_checked_time, mtime, [skills])
_RESUME_SKILL_CACHE: Dict[str, Tuple[float, float, List[str]]] = {}


def clear_keyword_cache():
    """Clears the in-memory resume keyword cache."""
    global _RESUME_SKILL_CACHE
    _RESUME_SKILL_CACHE.clear()


def extract_skills_from_resume_text(text: str) -> List[str]:
    """
    Extracts atomic technical skills from resume text.
    Prioritizes dedicated skills/competencies sections to avoid false positive
    skill matches from historical employment titles or narrative text.
    """
    if not text:
        return []

    # Try extracting from dedicated technical skills section
    skills_sec_match = re.search(
        r'(?:TECHNICAL\s+SKILLS|SKILLS|CORE\s+COMPETENCIES)\s*[\r\n]+(.*?)(?:[\r\n]+[A-Z\s]{4,}[\r\n]+|$)',
        text,
        re.DOTALL | re.IGNORECASE
    )
    if skills_sec_match and len(skills_sec_match.group(1).strip()) > 30:
        search_target = skills_sec_match.group(1).strip()
    else:
        search_target = text

    norm_target = normalize_text(search_target)

    matched = []
    for skill in MASTER_SKILL_VOCABULARY:
        pat = get_word_pattern(skill)
        if pat.search(norm_target):
            # Canonicalize or keep clean atomic name
            canon = ontology.get_canonical_skill(skill)
            matched.append(canon if canon else skill)

    # Deduplicate while preserving order
    return ontology.deduplicate_skills(matched)


def resolve_resume_path(role_title: str, config: Optional[dict] = None) -> Optional[str]:
    """Resolves absolute path to resume for a given role title."""
    if config is None:
        from core.scorer import load_latest_config
        config = load_latest_config()

    roles = config.get("ROLES", [])
    rt_clean = (role_title or "").strip().lower()

    # 1. Look in config ROLES
    for r in roles:
        title = r.get("title", "").strip().lower()
        if title == rt_clean or (title and title in rt_clean) or (rt_clean and rt_clean in title):
            resume_path = r.get("resume_path")
            if resume_path:
                clean_p = resume_path.strip()
                if not os.path.isabs(clean_p):
                    clean_p = os.path.join(BASE_DIR, clean_p)
                return os.path.abspath(clean_p)
            elif "RESUME_KEYWORDS" in config:
                # Role explicitly defined in config without resume_path, prefer config["RESUME_KEYWORDS"]
                return None

    # 2. Fall back to applicant_profile's get_resume_for_role only if config doesn't specify RESUME_KEYWORDS
    if "RESUME_KEYWORDS" not in config:
        try:
            from core.applicant_profile import get_resume_for_role
            p = get_resume_for_role(role_title)
            if p:
                clean_p = p.strip()
                if not os.path.isabs(clean_p):
                    clean_p = os.path.join(BASE_DIR, clean_p)
                return os.path.abspath(clean_p)
        except Exception as e:
            logging.debug(f"Could not load resume from profile for '{role_title}': {e}")

    return None


def get_resume_keywords_for_role(role_title: str, config: Optional[dict] = None) -> List[str]:
    """
    Dynamically loads and extracts atomic technical skills for a specific role.
    Caches extracted keywords keyed by file path and mtime. Auto-refreshes if
    the underlying resume PDF is modified.
    """
    resume_path = resolve_resume_path(role_title, config=config)

    if resume_path and os.path.exists(resume_path):
        try:
            mtime = os.path.getmtime(resume_path)
            if resume_path in _RESUME_SKILL_CACHE:
                cached_mtime, cached_skills = _RESUME_SKILL_CACHE[resume_path]
                if cached_mtime == mtime:
                    return cached_skills

            # Extract from PDF file
            raw_text = extract_text_from_file(resume_path)
            skills = extract_skills_from_resume_text(raw_text)
            if skills:
                _RESUME_SKILL_CACHE[resume_path] = (mtime, skills)
                return skills
        except Exception as e:
            logging.error(f"Error parsing resume at '{resume_path}': {e}")

    # Fallback if resume cannot be parsed or resolved
    if config:
        return config.get("RESUME_KEYWORDS", [])
    from core.scorer import load_latest_config
    cfg = load_latest_config()
    return cfg.get("RESUME_KEYWORDS", [])


def get_all_role_keywords(config: Optional[dict] = None) -> Dict[str, List[str]]:
    """Returns mapping of role title to its extracted resume keywords."""
    if config is None:
        from core.scorer import load_latest_config
        config = load_latest_config()

    roles = config.get("ROLES", [])
    res = {}
    for r in roles:
        title = r.get("title", "")
        if title:
            res[title] = get_resume_keywords_for_role(title, config=config)
    return res


def get_unified_resume_keywords(config: Optional[dict] = None) -> List[str]:
    """Returns the deduplicated union of all resume keywords across configured roles."""
    role_kws = get_all_role_keywords(config=config)
    unified = []
    seen = set()
    for kws in role_kws.values():
        for kw in kws:
            canon = ontology.get_canonical_skill(kw)
            if canon not in seen:
                seen.add(canon)
                unified.append(kw)

    if not unified and config:
        return config.get("RESUME_KEYWORDS", [])
    return unified
