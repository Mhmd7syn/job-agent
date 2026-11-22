import os
import sys
import json
import pytest
from unittest.mock import patch, MagicMock

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.email_signature import (
    get_signature_path_from_config,
    get_signature_html,
    get_signature_text,
    get_signature_from_config,
    format_email_body_html
)


@pytest.fixture
def temp_signature_files(tmp_path):
    # Global signature
    global_sig = tmp_path / "global_sig.html"
    global_sig.write_text(
        "<html><body><p><b>General Candidate</b><br>Software Engineer</p></body></html>",
        encoding="utf-8"
    )

    # Role-specific signature for Computer Vision
    cv_sig = tmp_path / "cv_sig.html"
    cv_sig.write_text(
        "<html><body><div><h3>Computer Vision Specialist</h3><p>Deep Learning & Edge AI</p></div></body></html>",
        encoding="utf-8"
    )

    # Role-specific signature for Data Analyst
    da_sig = tmp_path / "da_sig.html"
    da_sig.write_text(
        "<html><body><div><h3>Data & BI Analyst</h3><p>PowerBI & SQL</p></div></body></html>",
        encoding="utf-8"
    )

    return {
        "global": str(global_sig),
        "cv": str(cv_sig),
        "da": str(da_sig)
    }


def test_role_specific_signature_resolution(temp_signature_files):
    """Verify that role-specific signatures are prioritized over global signature."""
    mock_profile = {
        "auto_apply_settings": {
            "email_signature_path": temp_signature_files["global"],
            "signatures_by_role": {
                "Computer Vision & AI": temp_signature_files["cv"],
                "Data Analytics & BI": temp_signature_files["da"]
            }
        }
    }

    # Query with Computer Vision role -> returns CV signature
    cv_path = get_signature_path_from_config(mock_profile, target_role="Senior Computer Vision Engineer")
    assert cv_path == temp_signature_files["cv"]

    cv_html = get_signature_html(mock_profile, target_role="Senior Computer Vision Engineer")
    assert "Computer Vision Specialist" in cv_html
    assert "General Candidate" not in cv_html

    # Query with Data Analytics role -> returns DA signature
    da_path = get_signature_path_from_config(mock_profile, target_role="Lead Data Analyst")
    assert da_path == temp_signature_files["da"]

    da_html = get_signature_html(mock_profile, target_role="Lead Data Analyst")
    assert "Data & BI Analyst" in da_html
    assert "General Candidate" not in da_html

    # Query with unmatched role -> falls back to global signature
    fallback_path = get_signature_path_from_config(mock_profile, target_role="Product Manager")
    assert fallback_path == temp_signature_files["global"]

    fallback_html = get_signature_html(mock_profile, target_role="Product Manager")
    assert "General Candidate" in fallback_html


def test_signature_html_auto_discovery_when_unconfigured(tmp_path, monkeypatch):
    """Verify auto-discovery of signature.html in project root when no path is configured in profile."""
    fake_root_sig = tmp_path / "signature.html"
    fake_root_sig.write_text("<p>Auto Discovered Signature</p>", encoding="utf-8")

    monkeypatch.setattr("core.email_signature.BASE_DIR", str(tmp_path))

    empty_profile = {
        "auto_apply_settings": {
            "email_signature_path": "",
            "signatures_by_role": {}
        }
    }

    resolved_path = get_signature_path_from_config(empty_profile)
    assert resolved_path == str(fake_root_sig)

    resolved_html = get_signature_html(empty_profile)
    assert "Auto Discovered Signature" in resolved_html


def test_format_email_body_html_with_role_signature(temp_signature_files):
    """Verify format_email_body_html embeds role-specific HTML signature cleanly."""
    mock_profile = {
        "auto_apply_settings": {
            "email_signature_path": temp_signature_files["global"],
            "signatures_by_role": {
                "Computer Vision & AI": temp_signature_files["cv"]
            }
        }
    }

    with patch("core.email_signature.load_profile", return_value=mock_profile):
        body = "Dear Team,\n\nI am thrilled to apply for this opening.\n\nBest regards,\nTest"
        formatted_html = format_email_body_html(body, target_role="Computer Vision & AI")

        assert "Computer Vision Specialist" in formatted_html
        assert "Deep Learning & Edge AI" in formatted_html
        assert "General Candidate" not in formatted_html
        # Check that trailing Best regards was stripped to prevent duplicates
        assert formatted_html.count("Best regards") == 0


def test_plain_text_extraction_for_role_signature(temp_signature_files):
    """Verify get_signature_text extracts readable text from role-specific HTML."""
    mock_profile = {
        "auto_apply_settings": {
            "signatures_by_role": {
                "Computer Vision & AI": temp_signature_files["cv"]
            }
        }
    }

    text_sig = get_signature_text(mock_profile, target_role="Computer Vision & AI")
    assert "Computer Vision Specialist" in text_sig
    assert "Deep Learning & Edge AI" in text_sig
    assert "<div" not in text_sig
    assert "<p" not in text_sig
