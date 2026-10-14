import os
import sqlite3
import logging
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from core.database import DB_PATH
from core.applicant_profile import load_profile, save_profile
from appliers.email_worker import get_autopilot_state, run_email_autopilot_batch
from appliers.whatsapp_worker import run_whatsapp_autopilot_batch
from appliers.master_orchestrator import (
    run_master_autopilot_cycle,
    is_cycle_active,
    get_applications_history,
    get_applications_aggregate_stats,
    resolve_telegram_hitl_answer
)

router = APIRouter()
logger = logging.getLogger(__name__)


class RunCycleRequest(BaseModel):
    force: Optional[bool] = False
    dry_run: Optional[bool] = False

class ToggleAutoPilotRequest(BaseModel):
    enabled: bool

class RunEmailBatchRequest(BaseModel):
    force: Optional[bool] = False
    dry_run: Optional[bool] = False
    batch_limit: Optional[int] = None

class RunWhatsappBatchRequest(BaseModel):
    force: Optional[bool] = False
    dry_run: Optional[bool] = False
    batch_limit: Optional[int] = None

class HitlAnswerRequest(BaseModel):
    job_id: str
    question: str
    answer: str

class RetryApplicationRequest(BaseModel):
    job_id: str


@router.post("/api/autopilot/run-cycle")
def autopilot_run_cycle_endpoint(req: RunCycleRequest, bg_tasks: BackgroundTasks):
    if is_cycle_active():
        return {"status": "already_running", "message": "Auto-Pilot cycle is currently executing in background."}
    bg_tasks.add_task(run_master_autopilot_cycle, force=req.force or False, dry_run=req.dry_run or False)
    return {"status": "started", "message": "Master Auto-Pilot cycle dispatched to background."}

@router.get("/api/autopilot/status")
def autopilot_status_endpoint():
    state = get_autopilot_state()
    state["is_cycle_running"] = is_cycle_active()
    profile = load_profile()
    settings = profile.get("auto_apply_settings", {})
    is_enabled = bool(settings.get("enabled", False))
    state["is_enabled"] = is_enabled
    state["is_paused"] = not is_enabled
    return state

@router.post("/api/autopilot/toggle-state")
def autopilot_toggle_state_endpoint(req: ToggleAutoPilotRequest):
    profile = load_profile()
    if "auto_apply_settings" not in profile:
        profile["auto_apply_settings"] = {}
    profile["auto_apply_settings"]["enabled"] = req.enabled
    save_profile(profile)
    state_label = "Active / Resumed" if req.enabled else "Paused"
    return {
        "status": "success",
        "enabled": req.enabled,
        "is_paused": not req.enabled,
        "message": f"Auto-Pilot is now {state_label}."
    }

@router.post("/api/autopilot/run-email-batch")
def autopilot_run_email_batch_endpoint(req: RunEmailBatchRequest):
    return run_email_autopilot_batch(force=req.force or False, dry_run=req.dry_run or False, batch_limit=req.batch_limit)

@router.post("/api/autopilot/run-whatsapp-batch")
def autopilot_run_whatsapp_batch_endpoint(req: RunWhatsappBatchRequest):
    return run_whatsapp_autopilot_batch(force=req.force or False, dry_run=req.dry_run or False, batch_limit=req.batch_limit)

@router.get("/api/applications/history")
def applications_history_endpoint(
    channel: Optional[str] = "all",
    search: Optional[str] = "",
    limit: Optional[int] = 50,
    offset: Optional[int] = 0
):
    return get_applications_history(
        channel_filter=channel,
        search_query=search,
        limit=limit or 50,
        offset=offset or 0
    )

@router.get("/api/applications/stats")
def applications_stats_endpoint():
    return get_applications_aggregate_stats()

@router.post("/api/applications/retry")
def applications_retry_endpoint(req: RetryApplicationRequest):
    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=500, detail="Database not found")
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE jobs
            SET is_applied = 0,
                apply_status = 'pending'
            WHERE job_id = ?
        """, (req.job_id,))
        conn.commit()
        conn.close()
        return {"status": "success", "message": f"Job {req.job_id} reset to pending application state."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/autopilot/hitl-answer")
def autopilot_hitl_answer_endpoint(req: HitlAnswerRequest):
    success = resolve_telegram_hitl_answer(job_id=req.job_id, question=req.question, answer=req.answer)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to save HITL answer")
    return {"status": "success", "message": "Answer saved and application resumed."}
