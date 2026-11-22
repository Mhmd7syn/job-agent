import os
import sys
import json
import pytest
from unittest.mock import patch, MagicMock

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.applicant_profile import CandidateProfile, WritingStyleSettings, load_profile, save_profile
from appliers.email_generator import generate_email_draft
from appliers.whatsapp_copilot import generate_whatsapp_pitch


def test_writing_style_schema_defaults_and_custom():
    default_style = WritingStyleSettings()
    assert default_style.tone == "Direct & Professional"
    assert default_style.sample_writing == ""

    custom_style = WritingStyleSettings(
        tone="Technical & Detailed",
        sample_writing="Hi team, I built a multi-GPU distributed vision pipeline."
    )
    assert custom_style.tone == "Technical & Detailed"
    assert "multi-GPU" in custom_style.sample_writing

    profile = CandidateProfile(writing_style=custom_style)
    dumped = profile.model_dump()
    assert dumped["writing_style"]["tone"] == "Technical & Detailed"
    assert "multi-GPU" in dumped["writing_style"]["sample_writing"]


def test_email_generator_includes_tone_and_writing_sample():
    sample_job = {
        "job_id": "test-style-job-1",
        "title": "Computer Vision Engineer",
        "company": "DeepVision Labs",
        "location": "Cairo",
        "description": "Looking for a CV Engineer with PyTorch experience.",
        "apply_payload": {"recipient_email": "hr@deepvision.com", "subject_hint": ""}
    }

    mock_profile = {
        "personal_info": {"full_name": "Test Candidate"},
        "auto_apply_settings": {"email_signature_path": ""},
        "writing_style": {
            "tone": "Warm & Conversational",
            "sample_writing": "Hey there! Really excited about what you are building with edge vision."
        }
    }

    mock_response = MagicMock()
    mock_response.text = json.dumps({"body": "Hi Team,\n\nI saw your post and wanted to reach out."})

    with patch("appliers.email_generator.client") as mock_client, \
         patch("appliers.email_generator.load_profile", return_value=mock_profile), \
         patch("appliers.email_generator.get_resume_for_role", return_value=None), \
         patch("appliers.email_generator.generate_content_resilient", return_value=(mock_response, "gemini-flash-lite")) as mock_gen:

        res = generate_email_draft(job_data=sample_job)
        assert res["status"] == "success"

        mock_gen.assert_called_once()
        user_prompt = mock_gen.call_args[1]["contents"]

        assert "PREFERRED TONE:\nWarm & Conversational" in user_prompt
        assert "CANDIDATE AUTHENTIC WRITING STYLE SAMPLE:" in user_prompt
        assert "Hey there! Really excited about what you are building with edge vision." in user_prompt


def test_whatsapp_pitch_includes_tone_and_writing_sample():
    sample_job = {
        "job_id": "test-style-job-2",
        "title": "Lead Data Scientist",
        "company": "Fintech Solutions",
        "location": "Remote",
        "description": "Looking for Lead Data Scientist.",
        "apply_payload": {"phone": "+201012345678"}
    }

    mock_profile = {
        "personal_info": {
            "full_name": "Test Candidate",
            "email": "cand@test.com",
            "phone": "+201012345678",
            "linkedin_url": "https://linkedin.com/in/cand"
        },
        "auto_apply_settings": {},
        "writing_style": {
            "tone": "Technical & Detailed",
            "sample_writing": "Engineered production fraud models saving $2M annually."
        }
    }

    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "greeting": "Hi Team,",
        "intro_sentence": "I noticed your opening for Lead Data Scientist.",
        "bullet_achievements": ["Built credit scoring models", "Trained XGBoost on 10M rows"],
        "closing_sentence": "I have attached my resume for your review.",
        "sign_off": "Best regards,\nTest Candidate"
    })

    with patch("appliers.whatsapp_copilot.client") as mock_client, \
         patch("appliers.whatsapp_copilot.load_profile", return_value=mock_profile), \
         patch("appliers.whatsapp_copilot.get_resume_for_role", return_value=None), \
         patch("appliers.whatsapp_copilot.generate_content_resilient", return_value=(mock_response, "gemini-flash-lite")) as mock_gen:

        pitch = generate_whatsapp_pitch(job_data=sample_job)
        assert pitch != ""

        mock_gen.assert_called_once()
        user_prompt = mock_gen.call_args[1]["contents"]

        assert "PREFERRED TONE:\nTechnical & Detailed" in user_prompt
        assert "CANDIDATE AUTHENTIC WRITING STYLE SAMPLE:" in user_prompt
        assert "Engineered production fraud models saving $2M annually." in user_prompt
