import re
import unicodedata
from functools import lru_cache
from typing import List, Set, Optional

# Protected short acronyms that must strictly use exact word boundaries
# and never be stemmed or matched as substrings of other words.
PROTECTED_ACRONYMS: Set[str] = {
    "ai", "ml", "dl", "cv", "cnn", "nlp", "llm", "gcp", "aws", "k8s",
    "sql", "bi", "rag", "ci/cd", "cicd", "eda", "kpi", "dax", "etl",
    "vit", "rnn", "lstm", "svm", "api", "rest"
}

# Words ending in 's' that are singular and must NOT be stripped of 's'
PROTECTED_SINGULARS: Set[str] = {
    "keras", "pandas", "redis", "status", "bias", "express", "postgres",
    "postgresql", "analytics", "statistics", "mathematics", "physics",
    "devops", "aws", "k8s", "business", "loss", "cross", "pass", "basis",
    "series", "species", "corpus", "ingress", "egress", "nodejs", "wordpress"
}

# Words ending in 'ing' that must NOT be stemmed
PROTECTED_INGS: Set[str] = {
    "spring", "string", "bing", "ring", "king", "wing", "embedding", "embeddings"
}

# Irregular noun plurals mapping to singular
IRREGULAR_PLURALS = {
    "analyses": "analysis",
    "matrices": "matrix",
    "indices": "index",
    "hypotheses": "hypothesis",
    "criteria": "criterion",
    "data": "data",
    "databases": "database",
    "codebases": "codebase",
    "knowledgebases": "knowledgebase",
    "processes": "process",
    "classes": "class",
    "branches": "branch",
    "technologies": "technology",
    "methodologies": "methodology",
    "libraries": "library",
    "queries": "query",
    "capabilities": "capability",
    "categories": "category",
    "properties": "property",
    "dependencies": "dependency",
    "repositories": "repository",
    "utilities": "utility",
    "entities": "entity",
    "strategies": "strategy",
    "priorities": "priority",
}

# Common irregular / standard verb mappings (participles / past tense / gerund -> base)
VERB_LEMMA_MAP = {
    "analyzing": "analyze",
    "analyzed": "analyze",
    "optimizing": "optimize",
    "optimized": "optimize",
    "developing": "develop",
    "developed": "develop",
    "training": "train",
    "trained": "train",
    "tuning": "tune",
    "tuned": "tune",
    "deploying": "deploy",
    "deployed": "deploy",
    "processing": "process",
    "processed": "process",
    "evaluating": "evaluate",
    "evaluated": "evaluate",
    "engineering": "engineer",
    "engineered": "engineer",
    "scraping": "scrape",
    "scraped": "scrape",
    "modelling": "model",
    "modeling": "model",
    "modeled": "model",
    "modelled": "model",
    "visualizing": "visualize",
    "visualized": "visualize",
    "learning": "learn",
    "learned": "learn",
    "programming": "program",
    "programmed": "program",
    "computing": "compute",
    "computed": "compute",
    "building": "build",
    "built": "build",
    "testing": "test",
    "tested": "test",
    "creating": "create",
    "created": "create",
    "implementing": "implement",
    "implemented": "implement",
    "managing": "manage",
    "managed": "manage",
    "teaching": "teach",
    "taught": "teach",
    "mentoring": "mentor",
    "mentored": "mentor",
    "extracting": "extract",
    "extracted": "extract",
    "configuring": "configure",
    "configured": "configure",
    "predicting": "predict",
    "predicted": "predict",
    "classifying": "classify",
    "classified": "classify",
    "integrating": "integrate",
    "integrated": "integrate",
}


# Precompiled patterns for compound variants
_RE_NODEJS = re.compile(r'\bnode[\.\s\-_]+js\b', re.IGNORECASE)
_RE_CICD = re.compile(r'\bci\s*[/\\_\-]\s*cd\b', re.IGNORECASE)
_RE_REST_API = re.compile(r'\brestful?\s*[/\\_\s]\s*api\b', re.IGNORECASE)
_RE_AB_TESTING = re.compile(r'\ba\s*[/\\_\-]\s*b\s+testing\b', re.IGNORECASE)
_RE_STAR_SCHEMA = re.compile(r'\bstar\s*[\-_]\s*schema\b', re.IGNORECASE)
_RE_UNET = re.compile(r'\bu\s*[\-_]\s*net\b', re.IGNORECASE)
_RE_SKLEARN = re.compile(r'\bscikit\s*[\-_]\s*learn\b', re.IGNORECASE)
_RE_HYPHEN_WORDS = re.compile(r'(?<=[a-zA-Z0-9])-(?=[a-zA-Z0-9])')
_RE_SLASH_WORDS = re.compile(r'(?<!ci)(?<!a)(?<!c)/(?!cd)(?!b)(?!c\+\+)')
_RE_SPACES = re.compile(r'\s+')


@lru_cache(maxsize=8192)
def lemmatize_word(word: str) -> str:
    """
    Inflectional lemmatizer for technical skills and English job text.
    Handles regular/irregular plurals and verb inflections while preserving
    acronyms and technical domain terms.
    """
    if not word or len(word) <= 2:
        return word

    w_lower = word.lower()

    if w_lower in PROTECTED_ACRONYMS or w_lower in PROTECTED_SINGULARS:
        return w_lower

    if w_lower in IRREGULAR_PLURALS:
        return IRREGULAR_PLURALS[w_lower]

    if w_lower in VERB_LEMMA_MAP:
        return VERB_LEMMA_MAP[w_lower]

    # Plural normalization (-ies -> -y)
    if w_lower.endswith("ies") and len(w_lower) > 4:
        return w_lower[:-3] + "y"

    # Plural normalization (-es -> -)
    if w_lower.endswith("es") and len(w_lower) > 4:
        if w_lower.endswith(("sses", "shes", "ches", "xes", "zes")):
            return w_lower[:-2]
        if w_lower.endswith("bases"):
            return w_lower[:-1]
        return w_lower[:-1]

    # General plural (-s -> -)
    if w_lower.endswith("s") and not w_lower.endswith("ss") and len(w_lower) > 3:
        return w_lower[:-1]

    # Verb participle (-ing)
    if w_lower.endswith("ing") and len(w_lower) > 5 and w_lower not in PROTECTED_INGS:
        stem = w_lower[:-3]
        if stem.endswith(("iz", "at", "ut", "or", "ur", "sc", "clos")):
            return stem + "e"
        return stem

    # Past tense (-ed)
    if w_lower.endswith("ed") and len(w_lower) > 5:
        stem = w_lower[:-2]
        if stem.endswith(("iz", "at", "ut", "or", "ur", "sc", "clos")):
            return stem + "e"
        return stem

    return w_lower


def normalize_compound_variants(text: str) -> str:
    """
    Harmonizes compound terms like 'machine-learning' -> 'machine learning',
    'rest/api' -> 'rest api', 'node.js' -> 'nodejs', 'ci/cd' -> 'ci/cd'.
    """
    if not text:
        return ""

    t = text.lower()
    t = _RE_NODEJS.sub('nodejs', t)
    t = _RE_CICD.sub('ci/cd', t)
    t = _RE_REST_API.sub('rest api', t)
    t = _RE_AB_TESTING.sub('a/b testing', t)
    t = _RE_STAR_SCHEMA.sub('star schema', t)
    t = _RE_UNET.sub('u-net', t)
    t = _RE_SKLEARN.sub('scikit-learn', t)
    t = _RE_HYPHEN_WORDS.sub(' ', t)
    t = _RE_SLASH_WORDS.sub(' ', t)

    return t


def normalize_text(text: str) -> str:
    """
    Full text normalizer:
    1. Unicodedata normalization (NFKD to ASCII compatible)
    2. Lowercasing
    3. Compound word variant harmonization
    4. Collapse extraneous whitespace
    """
    if not text:
        return ""

    normalized = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
    normalized = normalize_compound_variants(normalized)
    normalized = _RE_SPACES.sub(' ', normalized).strip()
    return normalized


@lru_cache(maxsize=4096)
def normalize_phrase(phrase: str) -> str:
    """
    Normalizes a phrase or skill name by normalizing compound terms and
    lemmatizing each word.
    """
    cleaned = normalize_text(phrase)
    words = cleaned.split()
    lemmatized = [lemmatize_word(w) for w in words]
    return " ".join(lemmatized)


@lru_cache(maxsize=1024)
def get_word_pattern(term: str) -> re.Pattern:
    """
    Returns a compiled regex for strict word-boundary token matching.
    Supports technical symbols such as 'c++', 'c#', '.net', 'node.js', 'ci/cd'.
    Ensures short acronyms ('ai', 'ml', 'dl', 'cv', 'bi') never match inside
    words like 'claim', 'training', 'email', 'habit', 'html'.
    """
    term_clean = term.strip().lower()
    escaped = re.escape(term_clean)

    # If term starts with word char, require non-word char before it
    prefix = r'(?<![a-zA-Z0-9_])' if re.match(r'^[a-zA-Z0-9_]', term_clean) else ''
    # If term ends with word char, require non-word char after it
    suffix = r'(?![a-zA-Z0-9_])' if re.search(r'[a-zA-Z0-9_]$', term_clean) else ''

    return re.compile(prefix + escaped + suffix, re.IGNORECASE)


def contains_term(text: str, term: str, use_lemmatization: bool = True) -> bool:
    """
    Checks if text contains term with strict boundary matching and optional lemmatization.
    """
    if not text or not term:
        return False

    norm_text = normalize_text(text)
    norm_term = normalize_text(term)

    # 1. Direct regex match
    pattern = get_word_pattern(norm_term)
    if pattern.search(norm_text):
        return True

    # 2. Lemmatized phrase match if requested
    if use_lemmatization:
        lemma_text = normalize_phrase(text)
        lemma_term = normalize_phrase(term)
        if lemma_text != norm_text or lemma_term != norm_term:
            pattern_lemma = get_word_pattern(lemma_term)
            if pattern_lemma.search(lemma_text):
                return True

    return False
