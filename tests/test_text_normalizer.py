import pytest
from core.text_normalizer import (
    lemmatize_word,
    normalize_text,
    normalize_phrase,
    get_word_pattern,
    contains_term,
    PROTECTED_ACRONYMS,
    PROTECTED_SINGULARS
)

def test_plural_lemmatization():
    assert lemmatize_word("databases") == "database"
    assert lemmatize_word("technologies") == "technology"
    assert lemmatize_word("processes") == "process"
    assert lemmatize_word("libraries") == "library"
    assert lemmatize_word("queries") == "query"
    assert lemmatize_word("algorithms") == "algorithm"
    assert lemmatize_word("models") == "model"
    assert lemmatize_word("pipelines") == "pipeline"
    assert lemmatize_word("analyses") == "analysis"
    assert lemmatize_word("matrices") == "matrix"

def test_singular_and_tech_protection():
    # Singular words ending with 's' must be preserved
    assert lemmatize_word("keras") == "keras"
    assert lemmatize_word("pandas") == "pandas"
    assert lemmatize_word("redis") == "redis"
    assert lemmatize_word("status") == "status"
    assert lemmatize_word("analytics") == "analytics"
    assert lemmatize_word("statistics") == "statistics"
    assert lemmatize_word("devops") == "devops"
    assert lemmatize_word("aws") == "aws"
    assert lemmatize_word("k8s") == "k8s"
    assert lemmatize_word("business") == "business"

def test_verb_inflections():
    assert lemmatize_word("analyzing") == "analyze"
    assert lemmatize_word("developed") == "develop"
    assert lemmatize_word("training") == "train"
    assert lemmatize_word("tuning") == "tune"
    assert lemmatize_word("deploying") == "deploy"
    assert lemmatize_word("processing") == "process"
    assert lemmatize_word("evaluating") == "evaluate"
    assert lemmatize_word("engineering") == "engineer"
    assert lemmatize_word("testing") == "test"
    assert lemmatize_word("tested") == "test"

def test_compound_variants():
    assert normalize_text("Machine-Learning") == "machine learning"
    assert normalize_text("REST/API") == "rest api"
    assert normalize_text("Restful/API") == "rest api"
    assert normalize_text("Node.js") == "nodejs"
    assert normalize_text("CI/CD") == "ci/cd"
    assert normalize_text("Star-Schema") == "star schema"

def test_protected_acronym_isolation():
    ai_pat = get_word_pattern("ai")
    
    # Must match standalone or punctuated AI
    assert ai_pat.search("Senior AI Engineer") is not None
    assert ai_pat.search("Focusing on AI.") is not None
    assert ai_pat.search("AI/ML Specialist") is not None
    assert ai_pat.search("(AI) systems") is not None
    
    # MUST NOT match inside common English words
    assert ai_pat.search("Processing insurance claim") is None
    assert ai_pat.search("Extensive model training") is None
    assert ai_pat.search("Send email updates") is None
    assert ai_pat.search("System maintenance") is None
    assert ai_pat.search("In daily practice") is None
    assert ai_pat.search("Brain imaging") is None

    # Test ML isolation
    ml_pat = get_word_pattern("ml")
    assert ml_pat.search("Applied ML Researcher") is not None
    assert ml_pat.search("HTML5 and CSS") is None
    assert ml_pat.search("Seamless integration") is None
    assert ml_pat.search("Family healthcare") is None

    # Test CV isolation
    cv_pat = get_word_pattern("cv")
    assert cv_pat.search("Computer Vision (CV) Engineer") is not None
    assert cv_pat.search("Disaster recovery plan") is None
    assert cv_pat.search("Discovery channel") is None

    # Test BI isolation
    bi_pat = get_word_pattern("bi")
    assert bi_pat.search("Power BI Dashboard") is not None
    assert bi_pat.search("Mobile application") is None
    assert bi_pat.search("Habit tracker") is None
    assert bi_pat.search("Combine results") is None

def test_special_symbols_in_tokens():
    cpp_pat = get_word_pattern("c++")
    assert cpp_pat.search("Looking for C++ developer") is not None
    assert cpp_pat.search("Knowledge of C/C++ required") is not None
    assert cpp_pat.search("Experience with C programming") is None

    csharp_pat = get_word_pattern("c#")
    assert csharp_pat.search("Senior C# .NET Developer") is not None

def test_contains_term():
    text = "We are developing scalable databases and analyzing big datasets."
    assert contains_term(text, "develop")
    assert contains_term(text, "database")
    assert contains_term(text, "analyze")
    assert contains_term(text, "databases")
    assert not contains_term(text, "ai")
