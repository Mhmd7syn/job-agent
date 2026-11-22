import os
import sys
import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Ensure root dir is on path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from appliers.email_generator import generate_email_draft
from appliers.whatsapp_copilot import generate_whatsapp_pitch
import web.routers.copilots as copilots_router


@pytest.fixture
def mock_profile():
    return {
        "personal_info": {
            "full_name": "Test Candidate",
            "email": "candidate@example.com",
            "phone": "+201012345678",
            "linkedin_url": "https://linkedin.com/in/candidate"
        },
        "auto_apply_settings": {
            "smtp_email": "candidate@example.com",
            "signature": "Best regards,\nTest Candidate"
        }
    }


@pytest.fixture
def sample_job():
    return {
        "job_id": "test-job-instructions-1",
        "title": "Machine Learning Engineer",
        "company": "AI Pioneers",
        "location": "Cairo, Egypt",
        "description": "Looking for an ML engineer with PyTorch and distributed training experience.",
        "apply_payload": {
            "recipient_email": "careers@aipioneers.com",
            "phone": "+201099887766",
            "subject_hint": ""
        }
    }


def test_email_generator_appends_user_instructions(mock_profile, sample_job):
    """Verify that user_instructions are formatted and appended to the prompt in email generator."""
    instructions = "Focus heavily on PyTorch and distributed multi-GPU training. Keep tone direct and under 80 words."

    mock_response = MagicMock()
    mock_response.text = json.dumps({"body": "Dear Hiring Team,\n\nI am applying for the role.\n\nBest regards"})

    with patch("appliers.email_generator.client") as mock_client, \
         patch("appliers.email_generator.load_profile", return_value=mock_profile), \
         patch("appliers.email_generator.get_resume_for_role", return_value=None), \
         patch("core.database.save_job_generated_content"), \
         patch("appliers.email_generator.generate_content_resilient", return_value=(mock_response, "gemini-flash-lite-latest")) as mock_gen:

        res = generate_email_draft(job_data=sample_job, force_regenerate=True, user_instructions=instructions)

        assert res["status"] == "success"
        assert mock_gen.called

        # Verify the prompt contents passed to Gemini
        call_kwargs = mock_gen.call_args.kwargs
        contents = call_kwargs.get("contents", "")

        assert "ADDITIONAL USER INSTRUCTIONS/FOCUS:" in contents
        assert instructions in contents
        assert "Please adhere strictly to these instructions." in contents


def test_email_generator_without_instructions_no_extra_block(mock_profile, sample_job):
    """Verify that omitting user_instructions leaves the prompt clean without additional instructions block."""
    mock_response = MagicMock()
    mock_response.text = json.dumps({"body": "Dear Hiring Team,\n\nApplication body.\n\nBest regards"})

    with patch("appliers.email_generator.client") as mock_client, \
         patch("appliers.email_generator.load_profile", return_value=mock_profile), \
         patch("appliers.email_generator.get_resume_for_role", return_value=None), \
         patch("core.database.save_job_generated_content"), \
         patch("appliers.email_generator.generate_content_resilient", return_value=(mock_response, "gemini-flash-lite-latest")) as mock_gen:

        res = generate_email_draft(job_data=sample_job, force_regenerate=True, user_instructions=None)

        assert res["status"] == "success"
        assert mock_gen.called

        contents = mock_gen.call_args.kwargs.get("contents", "")
        assert "ADDITIONAL USER INSTRUCTIONS/FOCUS:" not in contents


def test_email_generator_instructions_bypasses_cache(mock_profile, sample_job):
    """Verify that providing user_instructions forces regeneration even if a cached draft exists."""
    cached_job = dict(sample_job)
    cached_job["apply_payload"] = {
        "recipient_email": "careers@aipioneers.com",
        "generated_email": {
            "subject": "Old Cached Subject",
            "body": "Old Cached Body",
            "raw_ai_body": "Old Cached Body",
            "generated_at": "2026-01-01T00:00:00"
        }
    }

    mock_response = MagicMock()
    mock_response.text = json.dumps({"body": "Newly generated draft with custom instructions"})

    with patch("appliers.email_generator.client") as mock_client, \
         patch("appliers.email_generator.load_profile", return_value=mock_profile), \
         patch("appliers.email_generator.get_resume_for_role", return_value=None), \
         patch("core.database.save_job_generated_content"), \
         patch("appliers.email_generator.generate_content_resilient", return_value=(mock_response, "gemini-flash-lite-latest")) as mock_gen:

        res = generate_email_draft(
            job_data=cached_job,
            force_regenerate=False,
            user_instructions="Emphasize deep learning research"
        )

        assert res["status"] == "success"
        # It should not return the old cached body
        assert res["raw_ai_body"] == "Newly generated draft with custom instructions"
        assert mock_gen.called


def test_whatsapp_copilot_appends_user_instructions(mock_profile, sample_job):
    """Verify that user_instructions are formatted and appended to the prompt in WhatsApp copilot."""
    instructions = "Keep under 40 words, very casual and mobile-friendly tone."

    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "greeting": "Hi AI Pioneers Team,",
        "introduction": "Reaching out regarding the ML Engineer role.",
        "key_highlights_used": ["Trained models with PyTorch"],
        "closing_and_attachment": "Resume attached.",
        "signature": "Best,\nTest Candidate",
        "pitch": "Hi AI Pioneers Team,\n\nReaching out for the ML role.\n\n• Trained models with PyTorch\n\nCV attached.\n\nTest"
    })

    with patch("appliers.whatsapp_copilot.client") as mock_client, \
         patch("appliers.whatsapp_copilot.load_profile", return_value=mock_profile), \
         patch("appliers.whatsapp_copilot.get_resume_for_role", return_value=None), \
         patch("core.database.save_job_generated_content"), \
         patch("appliers.whatsapp_copilot.generate_content_resilient", return_value=(mock_response, "gemini-flash-lite-latest")) as mock_gen:

        res = generate_whatsapp_pitch(job_data=sample_job, force_regenerate=True, user_instructions=instructions)

        assert res["status"] == "success"
        assert mock_gen.called

        contents = mock_gen.call_args.kwargs.get("contents", "")
        assert "ADDITIONAL USER INSTRUCTIONS/FOCUS:" in contents
        assert instructions in contents
        assert "Please adhere strictly to these instructions." in contents


def test_whatsapp_copilot_without_instructions_no_extra_block(mock_profile, sample_job):
    """Verify that omitting user_instructions in WhatsApp copilot leaves the prompt clean."""
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "pitch": "Hello,\n\nReaching out for the role.\n\nBest,\nTest",
        "key_highlights_used": []
    })

    with patch("appliers.whatsapp_copilot.client") as mock_client, \
         patch("appliers.whatsapp_copilot.load_profile", return_value=mock_profile), \
         patch("appliers.whatsapp_copilot.get_resume_for_role", return_value=None), \
         patch("core.database.save_job_generated_content"), \
         patch("appliers.whatsapp_copilot.generate_content_resilient", return_value=(mock_response, "gemini-flash-lite-latest")) as mock_gen:

        res = generate_whatsapp_pitch(job_data=sample_job, force_regenerate=True, user_instructions=None)

        assert res["status"] == "success"
        assert mock_gen.called

        contents = mock_gen.call_args.kwargs.get("contents", "")
        assert "ADDITIONAL USER INSTRUCTIONS/FOCUS:" not in contents


def test_whatsapp_copilot_instructions_bypasses_cache(mock_profile, sample_job):
    """Verify that providing user_instructions forces regeneration even if a cached pitch exists."""
    cached_job = dict(sample_job)
    cached_job["apply_payload"] = {
        "phone": "+201099887766",
        "generated_whatsapp": {
            "pitch": "Old Cached WhatsApp Pitch",
            "key_highlights_used": [],
            "phone": "201099887766",
            "generated_at": "2026-01-01T00:00:00"
        }
    }

    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "pitch": "New Pitch with custom focus",
        "key_highlights_used": []
    })

    with patch("appliers.whatsapp_copilot.client") as mock_client, \
         patch("appliers.whatsapp_copilot.load_profile", return_value=mock_profile), \
         patch("appliers.whatsapp_copilot.get_resume_for_role", return_value=None), \
         patch("core.database.save_job_generated_content"), \
         patch("appliers.whatsapp_copilot.generate_content_resilient", return_value=(mock_response, "gemini-flash-lite-latest")) as mock_gen:

        res = generate_whatsapp_pitch(
            job_data=cached_job,
            force_regenerate=False,
            user_instructions="Mention AWS SageMaker"
        )

        assert res["status"] == "success"
        assert "New Pitch with custom focus" in res["pitch"]
        assert mock_gen.called


def test_api_email_endpoint_passes_user_instructions():
    """Verify EmailDraftRequest parses user_instructions and generate_email_draft_endpoint forwards them."""
    from web.routers.copilots import EmailDraftRequest, generate_email_draft_endpoint

    req = EmailDraftRequest(
        job_id="job-100",
        force_regenerate=True,
        user_instructions="Focus on PyTorch"
    )
    assert req.user_instructions == "Focus on PyTorch"

    mock_draft = {
        "status": "success",
        "subject": "Application: ML Engineer",
        "body": "Draft body text",
        "raw_ai_body": "Draft body text"
    }

    with patch("web.routers.copilots.generate_email_draft", return_value=mock_draft) as mock_fn:
        res = generate_email_draft_endpoint(req)
        assert res["status"] == "success"
        mock_fn.assert_called_once_with(
            job_id="job-100",
            force_regenerate=True,
            user_instructions="Focus on PyTorch"
        )


def test_api_whatsapp_endpoint_passes_user_instructions():
    """Verify WhatsAppPitchRequest parses user_instructions and generate_whatsapp_pitch_endpoint forwards them."""
    from web.routers.copilots import WhatsAppPitchRequest, generate_whatsapp_pitch_endpoint

    req = WhatsAppPitchRequest(
        job_id="job-200",
        force_regenerate=True,
        user_instructions="Keep under 50 words"
    )
    assert req.user_instructions == "Keep under 50 words"

    mock_pitch = {
        "status": "success",
        "pitch": "Recruiter message pitch",
        "phone": "201012345678"
    }

    with patch("web.routers.copilots.generate_whatsapp_pitch", return_value=mock_pitch) as mock_fn:
        res = generate_whatsapp_pitch_endpoint(req)
        assert res["status"] == "success"
        mock_fn.assert_called_once_with(
            job_id="job-200",
            force_regenerate=True,
            user_instructions="Keep under 50 words"
        )
