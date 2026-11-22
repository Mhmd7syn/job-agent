import os
import sys
import json
import sqlite3
import pytest
from unittest.mock import MagicMock, patch

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.database import (
    DB_PATH,
    init_db,
    save_or_update_job,
    get_job_by_id,
    save_job_generated_content,
    get_job_generated_content,
    prune_unapplied_proposals,
    get_unapplied_proposals_count,
    MAX_STORED_PROPOSALS
)
from appliers.email_generator import generate_email_draft
from appliers.whatsapp_copilot import generate_whatsapp_pitch
from appliers.screening_resolver import ScreeningResolver
from appliers.master_orchestrator import resolve_whatsapp_hitl_answer


@pytest.fixture(autouse=True)
def setup_test_db():
    """Ensure database is initialized and create a clean test job."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Insert or reset test jobs
    cursor.execute("DELETE FROM jobs WHERE job_id LIKE 'test_saved_%'")
    conn.commit()
    conn.close()

    test_email_job = {
        "job_id": "test_saved_email_job_1",
        "title": "Software Engineer",
        "company": "Test Company",
        "location": "Cairo, Egypt",
        "job_url": "https://example.com/job/test1",
        "apply_type": "email",
        "apply_payload": {
            "recipient_email": "hr@testcompany.com",
            "subject_hint": "Application for Software Engineer"
        },
        "status": "pending"
    }
    save_or_update_job(test_email_job)

    test_wa_job = {
        "job_id": "test_saved_wa_job_1",
        "title": "Data Analyst",
        "company": "DataCorp",
        "location": "Cairo, Egypt",
        "job_url": "https://example.com/job/test2",
        "apply_type": "whatsapp",
        "apply_payload": {
            "phone": "+201012345678",
            "whatsapp_url": "https://wa.me/201012345678"
        },
        "status": "pending"
    }
    save_or_update_job(test_wa_job)

    yield

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM jobs WHERE job_id LIKE 'test_saved_%'")
    conn.commit()
    conn.close()


def test_database_save_and_get_job_generated_content():
    """Verify core helper saves and retrieves generated email, whatsapp pitch, and question answers."""
    job_id = "test_saved_email_job_1"
    
    success = save_job_generated_content(
        job_id=job_id,
        generated_email={"subject": "Test Subj", "body": "Test Body"},
        generated_whatsapp={"pitch": "Test Pitch", "phone": "201012345678"},
        question_answers={"Years of Python experience?": "3 years"},
        generated_cover_letter="Cover letter body"
    )
    assert success is True

    saved = get_job_generated_content(job_id)
    assert saved["generated_email"]["subject"] == "Test Subj"
    assert saved["generated_email"]["body"] == "Test Body"
    assert saved["generated_whatsapp"]["pitch"] == "Test Pitch"
    assert saved["question_answers"]["Years of Python experience?"] == "3 years"
    assert saved["generated_cover_letter"] == "Cover letter body"

    # Merge additional question answers without overwriting existing
    save_job_generated_content(
        job_id=job_id,
        question_answers={"Willing to relocate?": "Yes"}
    )
    updated = get_job_generated_content(job_id)
    assert updated["question_answers"]["Years of Python experience?"] == "3 years"
    assert updated["question_answers"]["Willing to relocate?"] == "Yes"


def test_email_draft_saved_to_job_and_not_regenerated():
    """Verify generated email draft is saved to the job and reused on subsequent calls without Gemini API."""
    job_id = "test_saved_email_job_1"

    mock_response = MagicMock()
    mock_response.text = json.dumps({"body": "Dear Hiring Team,\n\nI am applying for the role.\n\nBest regards"})

    # First call: Generates via Gemini and saves to job
    with patch("appliers.email_generator.generate_content_resilient", return_value=(mock_response, "gemini-flash-lite")) as mock_gen:
        draft1 = generate_email_draft(job_id=job_id, force_regenerate=False)
        assert draft1["status"] == "success"
        assert draft1["is_saved"] is False
        assert "Dear Hiring Team" in draft1["body"]
        assert mock_gen.call_count == 1

    # Verify saved in SQLite database
    job = get_job_by_id(job_id)
    payload = job["apply_payload"]
    assert "generated_email" in payload
    assert "Dear Hiring Team" in payload["generated_email"]["body"]

    # Second call: Should return saved draft WITHOUT calling Gemini API!
    with patch("appliers.email_generator.generate_content_resilient") as mock_gen_2:
        draft2 = generate_email_draft(job_id=job_id, force_regenerate=False)
        assert draft2["status"] == "success"
        assert draft2["is_saved"] is True
        assert "Dear Hiring Team" in draft2["body"]
        mock_gen_2.assert_not_called()

    # Third call with force_regenerate=True: Should call Gemini API and update job
    mock_response_updated = MagicMock()
    mock_response_updated.text = json.dumps({"body": "Dear Hiring Team,\n\nUpdated new AI draft.\n\nBest regards"})
    with patch("appliers.email_generator.generate_content_resilient", return_value=(mock_response_updated, "gemini-flash-lite")) as mock_gen_3:
        draft3 = generate_email_draft(job_id=job_id, force_regenerate=True)
        assert draft3["status"] == "success"
        assert draft3["is_saved"] is False
        assert "Updated new AI draft" in draft3["body"]
        assert mock_gen_3.call_count == 1

    # Verify updated in database
    job_updated = get_job_by_id(job_id)
    assert "Updated new AI draft" in job_updated["apply_payload"]["generated_email"]["body"]


def test_whatsapp_pitch_saved_to_job_and_not_regenerated():
    """Verify generated WhatsApp pitch is saved to the job and reused on subsequent calls without Gemini API."""
    job_id = "test_saved_wa_job_1"

    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "greeting": "Hello DataCorp Team,",
        "introduction": "I am reaching out regarding the Data Analyst role.",
        "key_highlights_used": ["3 years Python experience", "Built data pipelines"],
        "closing_and_attachment": "I have attached my CV PDF.",
        "signature": "Best regards,\nTest Candidate",
        "pitch": "Hello DataCorp Team,\n\nI am reaching out regarding the Data Analyst role.\n\n• 3 years Python experience\n\nI have attached my CV PDF.\n\nBest regards,\nTest Candidate"
    })

    # First call: Generates via Gemini and saves to job
    with patch("appliers.whatsapp_copilot.generate_content_resilient", return_value=(mock_response, "gemini-flash-lite")) as mock_gen:
        pitch1 = generate_whatsapp_pitch(job_id=job_id, force_regenerate=False)
        assert pitch1["status"] == "success"
        assert pitch1["is_saved"] is False
        assert "Data Analyst" in pitch1["pitch"]
        assert mock_gen.call_count == 1

    # Verify saved in SQLite database
    job = get_job_by_id(job_id)
    payload = job["apply_payload"]
    assert "generated_whatsapp" in payload
    assert "Data Analyst" in payload["generated_whatsapp"]["pitch"]

    # Second call: Should return saved pitch WITHOUT calling Gemini API!
    with patch("appliers.whatsapp_copilot.generate_content_resilient") as mock_gen_2:
        pitch2 = generate_whatsapp_pitch(job_id=job_id, force_regenerate=False)
        assert pitch2["status"] == "success"
        assert pitch2["is_saved"] is True
        assert "Data Analyst" in pitch2["pitch"]
        mock_gen_2.assert_not_called()

    # Third call with force_regenerate=True: Should call Gemini and update job
    mock_response_updated = MagicMock()
    mock_response_updated.text = json.dumps({
        "pitch": "Hello DataCorp Team,\n\nBrand new regenerated WhatsApp pitch.\n\nBest regards"
    })
    with patch("appliers.whatsapp_copilot.generate_content_resilient", return_value=(mock_response_updated, "gemini-flash-lite")) as mock_gen_3:
        pitch3 = generate_whatsapp_pitch(job_id=job_id, force_regenerate=True)
        assert pitch3["status"] == "success"
        assert pitch3["is_saved"] is False
        assert "Brand new regenerated" in pitch3["pitch"]
        assert mock_gen_3.call_count == 1


def test_question_answers_saved_to_job_and_reused():
    """Verify screening question answers are saved to the job and reused without AI regeneration."""
    job_id = "test_saved_email_job_1"
    question = "Describe your experience building ETL pipelines"

    mock_resp = MagicMock()
    mock_resp.text = "In my previous role, I built daily Python and SQL ETL pipelines processing 50k rows."

    # First resolver instance with job_id
    resolver = ScreeningResolver(job_title="Software Engineer", job_location="Cairo, Egypt", job_id=job_id)
    with patch("appliers.screening_resolver.generate_content_resilient", return_value=(mock_resp, "gemini-flash-lite")) as mock_gen:
        ans1 = resolver.resolve_field_value(question, field_type="textarea")
        assert ans1 == "In my previous role, I built daily Python and SQL ETL pipelines processing 50k rows."
        assert mock_gen.call_count == 1

    # Verify answer is persisted to job in database
    job = get_job_by_id(job_id)
    assert "question_answers" in job["apply_payload"]
    assert job["apply_payload"]["question_answers"][question] == ans1

    # Second resolver instance for the same job: Must use saved answer without calling AI!
    resolver2 = ScreeningResolver(job_title="Software Engineer", job_location="Cairo, Egypt", job_id=job_id)
    with patch("appliers.screening_resolver.generate_content_resilient") as mock_gen_2:
        ans2 = resolver2.resolve_field_value(question, field_type="textarea")
        assert ans2 == ans1
        mock_gen_2.assert_not_called()


def test_hitl_question_resolution_saves_to_job_record():
    """Verify resolve_whatsapp_hitl_answer stores the answer to the job record in database."""
    job_id = "test_saved_wa_job_1"
    question = "Do you have experience with Snowflake?"
    answer = "Yes, 2 years creating staging tables and dimensional models in Snowflake."

    resolve_whatsapp_hitl_answer(job_id=job_id, question=question, answer=answer)

    job = get_job_by_id(job_id)
    assert job["pending_questions"] is None or job["pending_questions"] == "[]"
    assert "question_answers" in job["apply_payload"]
    assert job["apply_payload"]["question_answers"][question] == answer


def test_api_endpoints_for_saved_content():
    """Verify endpoint handlers for saving and retrieving drafts, pitches, and question answers."""
    from web.routers.copilots import (
        save_email_draft_endpoint,
        SaveEmailDraftRequest,
        save_whatsapp_pitch_endpoint,
        SaveWhatsAppPitchRequest,
        save_job_question_answers_endpoint,
        SaveQuestionAnswersRequest,
        get_job_generated_content_endpoint,
        save_ats_cover_letter_endpoint,
        SaveCoverLetterRequest
    )

    job_id = "test_saved_email_job_1"

    # 1. Save email draft via endpoint
    resp_email = save_email_draft_endpoint(SaveEmailDraftRequest(
        job_id=job_id,
        subject="API Saved Subject",
        body="API Saved Body",
        recipient="hr@testcompany.com"
    ))
    assert resp_email["status"] == "success"

    # 2. Save WhatsApp pitch via endpoint
    resp_wa = save_whatsapp_pitch_endpoint(SaveWhatsAppPitchRequest(
        job_id=job_id,
        pitch="API Saved Pitch",
        phone="+201012345678"
    ))
    assert resp_wa["status"] == "success"

    # 3. Save question answers via endpoint
    resp_qa = save_job_question_answers_endpoint(job_id=job_id, req=SaveQuestionAnswersRequest(
        answers={
            "Years of SQL experience?": "4 years",
            "Highest degree?": "Bachelor of Computer Science"
        }
    ))
    assert resp_qa["status"] == "success"

    # 4. Save cover letter via endpoint
    resp_cl = save_ats_cover_letter_endpoint(SaveCoverLetterRequest(
        job_id=job_id,
        cover_letter="API Saved Cover Letter"
    ))
    assert resp_cl["status"] == "success"

    # 5. Get all generated content via endpoint
    content = get_job_generated_content_endpoint(job_id=job_id)
    assert content["status"] == "success"
    assert content["generated_email"]["subject"] == "API Saved Subject"
    assert content["generated_whatsapp"]["pitch"] == "API Saved Pitch"
    assert content["question_answers"]["Years of SQL experience?"] == "4 years"
    assert content["generated_cover_letter"] == "API Saved Cover Letter"


def test_save_or_update_job_preserves_generated_content():
    """Verify that re-scraping/updating a job preserves existing generated email, whatsapp, and QA."""
    job_id = "test_saved_email_job_1"
    save_job_generated_content(
        job_id=job_id,
        generated_email={"subject": "Preserved Subj", "body": "Preserved Email Body"},
        generated_whatsapp={"pitch": "Preserved Pitch"},
        question_answers={"Test Q": "Test Ans"}
    )

    # Simulate scraper updating the job details
    update_data = {
        "job_id": job_id,
        "title": "Software Engineer",
        "company": "Test Company",
        "location": "Cairo, Egypt",
        "job_url": "https://example.com/job/test1",
        "description": "Updated job description text from scraper"
    }
    saved_dict, is_new = save_or_update_job(update_data)
    assert is_new is False

    job_after_update = get_job_by_id(job_id)
    payload = job_after_update["apply_payload"]
    assert payload["generated_email"]["body"] == "Preserved Email Body"
    assert payload["generated_whatsapp"]["pitch"] == "Preserved Pitch"
    assert payload["question_answers"]["Test Q"] == "Test Ans"


def test_prepare_easy_apply_and_ats_return_saved_content():
    """Verify prepare_easy_apply and prepare_ats_application return saved question_answers & cover_letter."""
    from appliers.easy_apply_copilot import prepare_easy_apply
    from appliers.ats_copilot import prepare_ats_application

    job_id = "test_saved_email_job_1"
    save_job_generated_content(
        job_id=job_id,
        question_answers={"Notice period?": "1 month"},
        generated_cover_letter="Pre-generated cover letter"
    )

    ea_data = prepare_easy_apply(job_id)
    assert ea_data["status"] == "success"
    assert ea_data["question_answers"]["Notice period?"] == "1 month"

    ats_data = prepare_ats_application(job_id)
    assert ats_data["status"] == "success"
    assert ats_data["question_answers"]["Notice period?"] == "1 month"
    assert ats_data["cover_letter"] == "Pre-generated cover letter"


def test_prune_unapplied_proposals_fifo_eviction():
    """Verify FIFO eviction caps active unapplied stored proposals at 50."""
    total_jobs = 55
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Pre-populate 55 unapplied jobs with sequential timestamps
    for i in range(total_jobs):
        jid = f"test_saved_fifo_job_{i:02d}"
        iso_ts = f"2026-01-01T10:{i:02d}:00"
        cursor.execute("""
            INSERT INTO jobs (job_id, title, company, location, job_url, apply_type, apply_payload, is_applied, apply_status, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, 'unapplied', ?)
        """, (
            jid,
            f"Test Title {i}",
            f"Company {i}",
            "Cairo",
            f"https://example.com/jobs/{i}",
            "email",
            json.dumps({"recipient_email": f"hr{i}@example.com"}),
            iso_ts
        ))
    conn.commit()
    conn.close()

    # Now sequentially generate content for all 55 jobs
    for i in range(total_jobs):
        jid = f"test_saved_fifo_job_{i:02d}"
        save_job_generated_content(
            job_id=jid,
            generated_email={"subject": f"Pitch {i}", "body": f"Body {i}"}
        )

    # Active unapplied proposals must not exceed MAX_STORED_PROPOSALS (50)
    assert get_unapplied_proposals_count() == MAX_STORED_PROPOSALS

    # The first 5 (oldest FIFO: 0 to 4) should have their staging proposal pruned
    for i in range(5):
        jid = f"test_saved_fifo_job_{i:02d}"
        job = get_job_by_id(jid)
        assert job is not None
        # Underlying job metadata and scraper payload must be preserved
        assert job["title"] == f"Test Title {i}"
        payload = job["apply_payload"]
        assert payload.get("recipient_email") == f"hr{i}@example.com"
        # Staging proposal fields must be pruned
        assert payload.get("generated_email") is None

    # The newest 50 (5 to 54) must retain their generated email proposal
    for i in range(5, total_jobs):
        jid = f"test_saved_fifo_job_{i:02d}"
        job = get_job_by_id(jid)
        payload = job["apply_payload"]
        assert payload.get("generated_email") is not None
        assert payload["generated_email"]["subject"] == f"Pitch {i}"


def test_prune_unapplied_proposals_preserves_applied_jobs():
    """Verify applied jobs retain permanent application history and are never pruned by FIFO eviction."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    applied_job_id = "test_saved_applied_job_1"
    cursor.execute("""
        INSERT INTO jobs (job_id, title, company, location, job_url, apply_type, apply_payload, is_applied, apply_status, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, 'applied', '2025-01-01T00:00:00')
    """, (
        applied_job_id,
        "Applied Job",
        "Applied Corp",
        "Cairo",
        "https://example.com/jobs/applied",
        "email",
        json.dumps({
            "recipient_email": "applied@example.com",
            "generated_email": {"subject": "Permanent Subject", "body": "Permanent Body"}
        })
    ))
    conn.commit()
    conn.close()

    # Run eviction with max_proposals = 0 (prune all unapplied proposals)
    pruned = prune_unapplied_proposals(max_proposals=0)

    # Applied job must remain 100% intact with its permanent proposal history
    applied_job = get_job_by_id(applied_job_id)
    assert applied_job is not None
    assert applied_job["is_applied"] == 1
    assert applied_job["apply_payload"]["generated_email"]["subject"] == "Permanent Subject"


def test_save_proposals_fifo_capping_pending_alerts(tmp_path, monkeypatch):
    """Verify core.config_tuner.save_proposals enforces FIFO ceiling on pending_alerts.json."""
    from core.config_tuner import save_proposals
    alert_file = tmp_path / "pending_alerts.json"
    monkeypatch.setattr("core.config_tuner._get_alert_path", lambda: str(alert_file))

    # Add 6 proposals with a cap of 4
    proposals = [
        {"field": "RESUME_KEYWORDS", "type": "add", "value": f"skill_{i}", "display_name": f"Skill {i}", "reason": "test"}
        for i in range(6)
    ]
    save_proposals(proposals, max_proposals=4)

    assert alert_file.exists()
    with open(alert_file, "r", encoding="utf-8") as f:
        stored = json.load(f)

    # Must be capped at 4
    assert len(stored) == 4
    # Oldest (skill_0, skill_1) evicted; newest (skill_2, skill_3, skill_4, skill_5) retained
    stored_values = [p["value"] for p in stored]
    assert stored_values == ["skill_2", "skill_3", "skill_4", "skill_5"]



