"""Smoke test for the 3 enhancements applied in the implementation plan."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import is_job_seen
from core.llm_parser import extract_json_ld

# ── Test 1: is_job_seen with unknown URL ─────────────────────────────────────
result = is_job_seen("https://notareal.url/job/999")
assert result == False, f"Expected False, got {result}"
print("  PASS  is_job_seen(unknown url) => False")

# ── Test 2: extract_json_ld with a valid JobPosting payload ──────────────────
html = (
    "<html><head>"
    '<script type="application/ld+json">{'
    '"@context": "https://schema.org",'
    '"@type": "JobPosting",'
    '"title": "Junior ML Engineer",'
    '"datePosted": "2026-07-01T00:00:00",'
    '"employmentType": "FULL_TIME",'
    '"hiringOrganization": {"@type": "Organization", "name": "Advansys"},'
    '"jobLocation": {"@type": "Place", "address": {"addressLocality": "Cairo", "addressCountry": "EG"}},'
    '"description": "<p>Great role for a junior engineer.</p>"'
    "}</script></head><body></body></html>"
)
data = extract_json_ld(html)
assert data is not None, "extract_json_ld returned None — expected a dict"
assert data["title"] == "Junior ML Engineer", f"Bad title: {data['title']}"
assert data["company"] == "Advansys", f"Bad company: {data['company']}"
assert data["job_type"] == "Full-time", f"Bad job_type: {data['job_type']}"
assert data["date_posted"] == "2026-07-01", f"Bad date: {data['date_posted']}"
assert "Cairo" in data["location"], f"Bad location: {data['location']}"
assert "junior engineer" in data["description"].lower(), f"Bad description: {data['description']}"
print("  PASS  extract_json_ld => title, company, job_type, date, location, description all correct")

# ── Test 3: extract_json_ld returns None for non-JobPosting pages ────────────
html_no_job = "<html><head><script type='application/ld+json'>{\"@type\": \"WebPage\"}</script></head></html>"
assert extract_json_ld(html_no_job) is None, "Should return None for non-JobPosting JSON-LD"
print("  PASS  extract_json_ld(non-JobPosting page) => None  (Gemini fallback triggered correctly)")

# ── Test 4: extract_json_ld returns None for pages with no JSON-LD ───────────
assert extract_json_ld("<html><body>No structured data here</body></html>") is None
print("  PASS  extract_json_ld(no JSON-LD page) => None")

print()
print("All smoke tests passed!")
