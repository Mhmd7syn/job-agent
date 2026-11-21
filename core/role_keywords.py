import os
import re
import json
import time
import logging
from typing import Dict, List, Optional, Tuple, Set
from pydantic import BaseModel, Field

from core.text_normalizer import normalize_text, get_word_pattern
from core.skill_ontology import ontology, DOMAIN_CLUSTERS
from core.cv_parser import extract_text_from_file
from core.gemini_client import get_gemini_client, generate_content_resilient

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_FILE = os.path.join(BASE_DIR, "state", "resume_keywords_cache.json")


class ResumeKeywordsExtractionSchema(BaseModel):
    keywords: List[str] = Field(
        description="Comprehensive list of atomic technical skills, tools, frameworks, libraries, programming languages, architectures, methodologies, and domain concepts explicitly demonstrated in the resume (in lowercase, e.g., 'python', 'pytorch', 'object detection', 'docker', 'ci/cd', 'transformers'). Extract atomic standalone terms only; do not compound them."
    )


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

def _load_disk_cache() -> Dict[str, Tuple[float, List[str]]]:
    """Loads cached resume keywords from disk if present."""
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        cache: Dict[str, Tuple[float, List[str]]] = {}
        for path, entry in data.items():
            if isinstance(entry, dict) and "mtime" in entry and "keywords" in entry:
                cache[path] = (float(entry["mtime"]), list(entry["keywords"]))
            elif isinstance(entry, (list, tuple)) and len(entry) == 2:
                cache[path] = (float(entry[0]), list(entry[1]))
        return cache
    except Exception as e:
        logging.debug(f"Could not load resume keyword cache from disk: {e}")
        return {}


def _save_disk_cache() -> None:
    """Persists in-memory resume keyword cache to disk."""
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        data = {
            path: {"mtime": mtime, "keywords": keywords}
            for path, (mtime, keywords) in _RESUME_SKILL_CACHE.items()
        }
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logging.debug(f"Could not save resume keyword cache to disk: {e}")


# Cache format: file_path -> (mtime, [skills])
_RESUME_SKILL_CACHE: Dict[str, Tuple[float, List[str]]] = _load_disk_cache()


def clear_keyword_cache():
    """Clears both in-memory and persistent resume keyword caches."""
    global _RESUME_SKILL_CACHE
    _RESUME_SKILL_CACHE.clear()
    if os.path.exists(CACHE_FILE):
        try:
            os.remove(CACHE_FILE)
        except OSError as e:
            logging.debug(f"Could not remove cache file {CACHE_FILE}: {e}")


def normalize_and_deduplicate_keywords(keywords: List[str]) -> List[str]:
    """
    Normalizes extracted keywords using skill_ontology canonicalization
    and deduplicates preserving order.
    """
    normalized = []
    for kw in keywords:
        if not kw or not isinstance(kw, str):
            continue
        clean_kw = kw.strip().lower()
        if not clean_kw:
            continue
        canon = ontology.get_canonical_skill(clean_kw)
        normalized.append(canon if canon else clean_kw)
    return ontology.deduplicate_skills(normalized)


def extract_keywords_with_gemini(raw_text: str) -> List[str]:
    """
    Extracts technical skills, tools, frameworks, methodologies, architectures,
    and domain concepts across the entire CV using Gemini LLM.
    """
    if not raw_text or not raw_text.strip():
        return []

    try:
        from google.genai import types

        client = get_gemini_client()
        if not client:
            return []

        prompt = f"""You are an expert technical talent recruiter and AI profiling assistant.
Analyze the following resume across its ENTIRE content (skills, work experience, projects, certifications, education).
Extract all explicit technical keywords, specifically:
- Programming Languages & Databases (e.g., Python, C++, SQL, MongoDB, PostgreSQL)
- Frameworks & Libraries (e.g., PyTorch, TensorFlow, Scikit-learn, React, FastAPI, Django, Pandas)
- Developer Tools, Cloud & DevOps (e.g., Git, Docker, Kubernetes, Linux, AWS, Azure, GCP, CI/CD, Airflow)
- Engineering Methodologies & Practices (e.g., Agile, Scrum, TDD, ETL, A/B Testing, Data Modeling)
- Domain Concepts & Core Competencies (e.g., Computer Vision, NLP, Deep Learning, Generative AI, RAG, Business Intelligence)
- Architectures & Patterns (e.g., Microservices, REST APIs, Transformers, CNN, ResNet, U-Net)

Strict Extraction Rules:
1. Extract atomic/standalone terms only (e.g., 'Python', 'FastAPI', 'Docker', 'Object Detection').
2. DO NOT combine or compound skills (e.g., NO 'Python Developer', NO 'ML Specialist').
3. DO NOT include generic soft skills or filler words (e.g., NO 'communication', 'leadership', 'teamwork', 'problem solving').
4. Output all keywords in lowercase.

Resume Text:
{raw_text[:15000]}
"""
        response, model_used = generate_content_resilient(
            client=client,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ResumeKeywordsExtractionSchema,
            ),
            preferred_model="gemini-flash-lite-latest",
        )

        raw_body = response.text.strip()
        if raw_body.startswith("```"):
            raw_body = re.sub(r"^```(?:json)?\s*", "", raw_body)
            raw_body = re.sub(r"\s*```$", "", raw_body)
        parsed = json.loads(raw_body)
        raw_kws = parsed.get("keywords", []) if isinstance(parsed, dict) else []
        if raw_kws:
            logging.info(f"Successfully extracted {len(raw_kws)} keywords via Gemini ({model_used})")
            return normalize_and_deduplicate_keywords(raw_kws)
    except Exception as e:
        logging.warning(f"Gemini CV keyword extraction failed or unavailable: {e}")

    return []


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


def extract_keywords_from_resume_path(resume_path: str, force_refresh: bool = False) -> List[str]:
    """
    Extracts, normalizes, and deduplicates keywords from the resume at resume_path.
    Uses Gemini LLM with ontology normalization, strictly caches by file mtime in-memory and on disk,
    and falls back to offline regex matcher if Gemini is unavailable.
    """
    if not resume_path or not resume_path.strip():
        return []

    clean_p = resume_path.strip()
    if not os.path.isabs(clean_p):
        clean_p = os.path.join(BASE_DIR, clean_p)
    abs_path = os.path.abspath(clean_p)

    if not os.path.exists(abs_path):
        return []

    try:
        mtime = os.path.getmtime(abs_path)
        if not force_refresh and abs_path in _RESUME_SKILL_CACHE:
            cached_mtime, cached_skills = _RESUME_SKILL_CACHE[abs_path]
            if cached_mtime == mtime:
                return cached_skills

        raw_text = extract_text_from_file(abs_path)
        skills = extract_keywords_with_gemini(raw_text)
        if not skills:
            skills = extract_skills_from_resume_text(raw_text)
        if skills:
            skills = normalize_and_deduplicate_keywords(skills)
            _RESUME_SKILL_CACHE[abs_path] = (mtime, skills)
            _save_disk_cache()
            return skills
    except Exception as e:
        logging.error(f"Error parsing resume at '{abs_path}': {e}")

    return []


def get_resume_keywords_for_role(role_title: str, config: Optional[dict] = None) -> List[str]:
    """
    Dynamically loads and extracts technical keywords for a specific role across the entire CV.
    Prioritizes explicit user-edited role.get("resume_keywords") if present, otherwise falls back
    to extracting keywords from the role's tailored CV.
    """
    if config is None:
        from core.scorer import load_latest_config
        config = load_latest_config()

    roles = config.get("ROLES", [])
    rt_clean = (role_title or "").strip().lower()

    # 1. Prioritize explicit user-edited role.get("resume_keywords") if present
    for r in roles:
        title = r.get("title", "").strip().lower()
        if title == rt_clean or (title and title in rt_clean) or (rt_clean and rt_clean in title):
            explicit_kws = r.get("resume_keywords")
            if explicit_kws is not None:
                return normalize_and_deduplicate_keywords(explicit_kws)
            break

    # 2. Fall back to CV extraction
    resume_path = resolve_resume_path(role_title, config=config)
    if resume_path:
        skills = extract_keywords_from_resume_path(resume_path, force_refresh=False)
        if skills:
            return skills

    # 3. Fallback if resume cannot be parsed or resolved
    return config.get("RESUME_KEYWORDS", [])


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

    if config and config.get("RESUME_KEYWORDS"):
        for kw in config.get("RESUME_KEYWORDS", []):
            canon = ontology.get_canonical_skill(kw)
            if canon not in seen:
                seen.add(canon)
                unified.append(kw)

    return unified
