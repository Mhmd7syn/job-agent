import json
from pathlib import Path

GOLD_DIR = Path(__file__).parent / "data" / "gold_standard"
MANIFEST_PATH = GOLD_DIR / "fixtures_manifest.json"


def test_gold_standard_manifest_structure_and_files():
    assert MANIFEST_PATH.exists(), f"Missing manifest at {MANIFEST_PATH}"
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    html_fixtures = manifest.get("html_fixtures", [])
    job_descriptions = manifest.get("job_descriptions", [])
    resumes = manifest.get("resumes", [])

    platforms = {item["platform"] for item in html_fixtures}
    assert {"wuzzuf", "bayt", "linkedin", "tanqeeb", "glassdoor"}.issubset(platforms)
    assert len(job_descriptions) >= 15
    assert len(resumes) >= 3

    for entry in html_fixtures:
        path = GOLD_DIR / entry["file"]
        assert path.exists() and path.read_text(encoding="utf-8").strip()
        assert entry["expected_apply_url"].startswith("https://")

    for entry in job_descriptions:
        path = GOLD_DIR / entry["file"]
        assert path.exists() and path.read_text(encoding="utf-8").strip()
        assert "title" in entry and "expected_canonical_skills" in entry

    for entry in resumes:
        path = GOLD_DIR / entry["file"]
        assert path.exists() and path.read_text(encoding="utf-8").strip()
        assert len(entry["expected_canonical_skills"]) >= 3
