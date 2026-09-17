"""
Canonical Career Seniority Levels and Synonym Expansion Engine.

Provides:
- Standardized career categories for UI checkboxes
- Comprehensive synonym dictionary for each category
- Helpers to expand categories/keywords and determine exclusions
"""

import re

CAREER_LEVEL_CATEGORIES = [
    "Intern / Student",
    "Fresh Graduate / Entry-level",
    "Junior",
    "Mid-Level",
    "Senior / Lead",
    "Manager / Director"
]

CAREER_LEVEL_SYNONYMS = {
    "Intern / Student": [
        "intern",
        "internship",
        "interns",
        "student",
        "trainee",
        "undergrad",
        "undergraduate",
        "co-op",
        "coop"
    ],
    "Fresh Graduate / Entry-level": [
        "fresh",
        "graduate",
        "fresh graduate",
        "fresh grad",
        "entry",
        "entry-level",
        "entry level",
        "entrylevel",
        "starter",
        "beginner",
        "trainee"
    ],
    "Junior": [
        "junior",
        "jr",
        "associate",
        "entry-to-mid",
        "junior-level",
        "junior level"
    ],
    "Mid-Level": [
        "mid",
        "mid-level",
        "mid level",
        "midlevel",
        "intermediate",
        "experienced"
    ],
    "Senior / Lead": [
        "senior",
        "sr",
        "lead",
        "principal",
        "staff",
        "architect",
        "expert",
        "tech lead",
        "team lead"
    ],
    "Manager / Director": [
        "manager",
        "director",
        "head",
        "vp",
        "vice president",
        "executive",
        "chief"
    ]
}

# Normalize lookup dictionary: map lowercase category and all synonyms to canonical category
KEYWORD_TO_CATEGORY = {}
for cat, syns in CAREER_LEVEL_SYNONYMS.items():
    KEYWORD_TO_CATEGORY[cat.lower()] = cat
    for syn in syns:
        KEYWORD_TO_CATEGORY[syn.lower()] = cat


def normalize_category_name(name: str) -> str:
    """Returns the canonical category name if matched, else the stripped string."""
    if not name:
        return ""
    clean = str(name).strip()
    return KEYWORD_TO_CATEGORY.get(clean.lower(), clean)


def expand_levels(levels: list[str]) -> set[str]:
    """
    Expands a list of categories and/or individual keywords into a flat set of lowercase synonyms.
    Supports:
    - Canonical category names (e.g. "Junior" -> {"junior", "jr", "associate", ...})
    - Legacy individual keywords (e.g. "intern" -> maps to "Intern / Student" and includes its synonyms)
    - Custom keywords not in standard taxonomy (retained as-is)
    """
    expanded = set()
    if not levels:
        return expanded

    for item in levels:
        if not item:
            continue
        item_str = str(item).strip().lower()
        if not item_str:
            continue

        # Check if item matches a canonical category name
        matched_category = None
        for cat in CAREER_LEVEL_CATEGORIES:
            if cat.lower() == item_str:
                matched_category = cat
                break

        if matched_category:
            for syn in CAREER_LEVEL_SYNONYMS.get(matched_category, []):
                expanded.add(syn.lower())
            expanded.add(matched_category.lower())
        else:
            # Check if this raw keyword belongs to a known category
            parent_category = KEYWORD_TO_CATEGORY.get(item_str)
            if parent_category:
                for syn in CAREER_LEVEL_SYNONYMS.get(parent_category, []):
                    expanded.add(syn.lower())
            # Always preserve the exact keyword itself
            expanded.add(item_str)

    return expanded


def get_excluded_levels(target_levels: list[str], explicit_level_exclude: list[str] = None) -> list[str]:
    """
    Determines which canonical categories should be excluded.
    If explicit_level_exclude is provided and non-empty, returns that.
    Otherwise, computes unchecked categories: all CAREER_LEVEL_CATEGORIES not represented in target_levels.
    """
    if explicit_level_exclude is not None and len(explicit_level_exclude) > 0:
        return [str(x).strip() for x in explicit_level_exclude if str(x).strip()]

    # Find canonical categories represented by target_levels
    included_categories = set()
    for item in target_levels or []:
        if not item:
            continue
        item_str = str(item).strip().lower()
        # Direct category match
        for cat in CAREER_LEVEL_CATEGORIES:
            if cat.lower() == item_str:
                included_categories.add(cat)
        # Reverse lookup by keyword
        parent = KEYWORD_TO_CATEGORY.get(item_str)
        if parent:
            included_categories.add(parent)

    excluded = [cat for cat in CAREER_LEVEL_CATEGORIES if cat not in included_categories]
    return excluded
