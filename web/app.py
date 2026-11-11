from fastapi import FastAPI, BackgroundTasks, HTTPException, Request, UploadFile, File, Query, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
import collections
import subprocess
import logging
import sys
import os
import json
import time
import tempfile
import uuid
import shutil
from datetime import datetime

# Add the parent directory to sys.path so we can import core modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import (
    get_jobs_by_status, update_job_status, get_job_by_id, toggle_job_applied,
    delete_job_by_id, save_or_update_job
)
from core.config_tuner import analyze_job_and_tune_config
from core.cv_parser import parse_cv_with_ai
from core.scorer import rescore_all_jobs
from scrapers.link_scraper import scrape_job_from_url
import core.config as app_config
from core.whatsapp_bot import (
    sync_queued_whatsapp_jobs, get_candidate_phone, enqueue_incoming_message,
    process_incoming_payload, normalize_phone_number
)

app = FastAPI(title="Job Dashboard")

# Mount static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
def read_root():
    return FileResponse(os.path.join(static_dir, "index.html"))

_last_rescore_date = None

@app.on_event("startup")
def on_startup():
    global _last_rescore_date
    try:
        rescore_all_jobs()
        _last_rescore_date = datetime.now().strftime("%Y-%m-%d")
    except Exception as e:
        logging.error(f"Failed to rescore jobs on startup: {e}")
    try:
        from core.task_scheduler import sync_autopilot_windows_task
        sync_autopilot_windows_task()
    except Exception as e:
        logging.error(f"Failed to synchronize AutoPilot Windows Task on startup: {e}")

@app.on_event("shutdown")
def on_shutdown():
    pass

@app.get("/api/jobs")
def get_jobs(background_tasks: BackgroundTasks, apply_type: Optional[str] = None):
    """Returns all jobs so the frontend can filter them by status and optional apply_type."""
    global _last_rescore_date
    today_str = datetime.now().strftime("%Y-%m-%d")
    if _last_rescore_date != today_str:
        background_tasks.add_task(rescore_all_jobs)
        _last_rescore_date = today_str
    jobs = get_jobs_by_status(['pending', 'liked', 'not_related'])
    if apply_type and apply_type != "all":
        target = apply_type.lower()
        if target == "easy_apply":
            jobs = [j for j in jobs if (j.get("apply_type") or "").lower() == "easy_apply" or (j.get("apply_channel") or "").lower() == "easy_apply" or j.get("is_easy_apply") in (1, True, "1", "true")]
        elif target == "manual":
            jobs = [j for j in jobs if (j.get("apply_type") or "manual").lower() == "manual" and (j.get("apply_channel") or "").lower() not in ("email", "whatsapp", "easy_apply", "form", "platform", "social_post", "job_board") and not j.get("is_easy_apply")]
        else:
            jobs = [j for j in jobs if (j.get("apply_type") or "").lower() == target or (j.get("apply_channel") or "").lower() == target]
    return {"jobs": jobs}

@app.api_route("/api/rescore", methods=["GET", "POST"])
def rescore_jobs():
    """Rescores all jobs in the database against latest criteria and date penalties."""
    global _last_rescore_date
    try:
        res = rescore_all_jobs()
        _last_rescore_date = datetime.now().strftime("%Y-%m-%d")
        return res
    except Exception as e:
        logging.error(f"Failed to rescore jobs: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class AddJobByUrlRequest(BaseModel):
    url: str = Field(default="")
    scraper_type: str = Field(default="auto")
    raw_text: str = Field(default="")
    is_scholarship: bool = Field(default=False)

@app.post("/api/jobs/add-by-url")
def add_job_by_url_endpoint(req: AddJobByUrlRequest):
    url = (req.url or "").strip()
    raw_text = (req.raw_text or "").strip()
    if not url and not raw_text:
        raise HTTPException(status_code=400, detail="Please provide a job URL or job post text.")

    try:
        job_dict = scrape_job_from_url(
            url=url,
            scraper_type=req.scraper_type,
            raw_text=raw_text,
            is_scholarship=req.is_scholarship
        )
        saved_job, is_new = save_or_update_job(job_dict, force_pending=True)
        return {
            "status": "success",
            "is_new": is_new,
            "job": saved_job
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logging.error(f"Error adding job by URL: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to scrape job: {str(e)}")

CONFIG_JSON_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'core', 'config.json')

@app.get("/api/config")
def get_config():
    config_path = CONFIG_JSON_PATH
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/config")
async def update_config(request: Request, background_tasks: BackgroundTasks):
    config_path = CONFIG_JSON_PATH
    try:
        new_config = await request.json()
        new_config["last_reviewed_date"] = datetime.now().strftime("%Y-%m-%d")
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(new_config, f, indent=2, ensure_ascii=False)
        
        app_config.reload_config()

        # Automatically rescore all jobs in the background with updated preferences
        background_tasks.add_task(rescore_all_jobs)

        return {"status": "success", "last_reviewed_date": new_config["last_reviewed_date"]}
    except Exception as e:
        logging.error(f"Error updating config: {e}")
        return {"status": "error", "error": str(e)}
ENV_FILE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")

class WhatsAppConfigRequest(BaseModel):
    phone_number: str = Field(default="")

@app.get("/api/whatsapp/status")
def get_whatsapp_status():
    phone = getattr(app_config, "WHATSAPP_PHONE_NUMBER", None) or os.getenv("WHATSAPP_PHONE_NUMBER", "") or get_candidate_phone()
    clean_p = normalize_phone_number(phone)
    chat_url = f"https://wa.me/{clean_p.lstrip('+')}" if clean_p else "https://web.whatsapp.com"
    return {
        "is_configured": bool(clean_p),
        "phone_number": clean_p,
        "chat_url": chat_url
    }

@app.post("/api/whatsapp/config")
def save_whatsapp_config(req: WhatsAppConfigRequest):
    new_phone = normalize_phone_number(req.phone_number.strip())
    env_path = ENV_FILE_PATH
    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    updated_phone = False
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("WHATSAPP_PHONE_NUMBER"):
            new_lines.append(f'WHATSAPP_PHONE_NUMBER="{new_phone}"\n')
            updated_phone = True
        elif stripped.startswith("TELEGRAM_"):
            continue
        else:
            new_lines.append(line)

    if not updated_phone:
        new_lines.append(f'WHATSAPP_PHONE_NUMBER="{new_phone}"\n')

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    app_config.WHATSAPP_PHONE_NUMBER = new_phone
    os.environ["WHATSAPP_PHONE_NUMBER"] = new_phone
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=env_path, override=True)
    except Exception:
        pass

    clean_digits = new_phone.lstrip('+')
    chat_url = f"https://wa.me/{clean_digits}" if clean_digits else "https://web.whatsapp.com"

    return {
        "status": "success",
        "phone_number": new_phone,
        "chat_url": chat_url,
        "message": f"WhatsApp phone {new_phone} saved." if new_phone else "WhatsApp phone cleared."
    }

@app.get("/api/whatsapp/sync")
def sync_whatsapp_endpoint():
    """Triggered on app launch or GUI reload to sync queued jobs in one shot."""
    return sync_queued_whatsapp_jobs()

@app.get("/api/whatsapp/check-new-jobs")
def check_new_whatsapp_jobs():
    return sync_queued_whatsapp_jobs()

@app.get("/api/whatsapp/webhook")
def whatsapp_webhook_verification(
    request: Request,
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge")
):
    params = request.query_params
    mode = hub_mode or params.get("hub_mode")
    verify_token = hub_verify_token or params.get("hub_verify_token")
    challenge = hub_challenge or params.get("hub_challenge")

    expected_token = getattr(app_config, "WHATSAPP_VERIFY_TOKEN", None) or os.getenv("WHATSAPP_VERIFY_TOKEN", "job_agent_verify_token")
    if mode == "subscribe" and verify_token == expected_token:
        return Response(content=challenge or "", media_type="text/plain", status_code=200)
    if not mode and challenge:
        return Response(content=challenge, media_type="text/plain", status_code=200)
    return Response(content="Verification failed", status_code=403)

@app.post("/api/whatsapp/webhook")
async def whatsapp_webhook_receiver(request: Request):
    payload = await request.json()
    res = process_incoming_payload(payload)
    return {"status": "received", "result": res}

from core.cv_parser import parse_cv_with_ai, generate_cv_proposals
from core.config_tuner import _get_alert_path, save_proposals, apply_config_updates

@app.post("/api/parse-cv")
async def parse_cv_endpoint(file: UploadFile = File(...)):
    """Uploads a CV file (PDF/DOCX/TXT), generates structured ADD/REMOVE proposals, and queues them for user review."""
    try:
        suffix = os.path.splitext(file.filename)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            shutil.copyfileobj(file.file, tmp)
            tmp_path = tmp.name
            
        result = parse_cv_with_ai(tmp_path)
        try:
            os.remove(tmp_path)
        except OSError as e:
            logging.warning(f"Could not delete temp CV file: {e}")

        if "error" in result and result.get("status") != "success":
            return result

        config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'core', 'config.json')
        config_data = {}
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)

        proposals = generate_cv_proposals(result, config_data)
        if proposals:
            save_proposals(proposals)

        return {
            "status": "success",
            "proposals": proposals,
            "user_brief": result.get("user_brief"),
            "engine": result.get("engine")
        }
    except Exception as e:
        logging.error(f"CV parsing error: {e}")
        return {"error": f"Failed to parse CV: {e}", "status": "error"}


@app.get("/api/status")
def get_status():
    """Returns the latest AI evaluation brief and the last few lines of the log."""
    output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
    eval_file = os.path.join(output_dir, "evaluation_brief.txt")
    log_file = os.path.join(output_dir, "job_agent.log")
    
    eval_text = "No evaluation available yet."
    if os.path.exists(eval_file):
        with open(eval_file, "r", encoding="utf-8") as f:
            eval_text = f.read()
            
    log_text = "No logs available."
    if os.path.exists(log_file):
        with open(log_file, "r", encoding="utf-8") as f:
            log_text = "".join(collections.deque(f, maxlen=20))
            
    return {"evaluation": eval_text, "logs": log_text}

@app.post("/api/jobs/{job_id}/apply")
def toggle_applied(job_id: str):
    """Toggles the is_applied boolean flag for a job."""
    job = get_job_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    
    new_state = 0 if job.get('is_applied') == 1 else 1
    toggle_job_applied(job_id, new_state)
    return {"status": "success", "job_id": job_id, "is_applied": new_state}

@app.post("/api/jobs/{job_id}/{action}")
def update_job(job_id: str, action: str, background_tasks: BackgroundTasks):
    """
    Updates a job's status and triggers the AI background task to tune the config.
    Valid actions: 'liked', 'not_related', 'pending'
    """
    valid_actions = ['liked', 'not_related', 'pending']
    if action not in valid_actions:
        raise HTTPException(status_code=400, detail="Invalid action.")

    job = get_job_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    update_job_status(job_id, action)
    
    # Trigger background AI task to extract keywords and tune the config
    background_tasks.add_task(analyze_job_and_tune_config, job, action)

    return {"status": "success", "job_id": job_id, "action": action}


@app.delete("/api/jobs/{job_id}")
def delete_single_job_endpoint(job_id: str):
    """Permanently deletes a single job by its ID."""
    success = delete_job_by_id(job_id)
    if not success:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {"status": "success", "job_id": job_id}


def is_process_running(pid: int) -> bool:
    """Verifies if a python scraper process with given PID is currently active on OS."""
    if not pid or pid <= 0:
        return False
    if os.name == 'nt':
        try:
            import ctypes
            import ctypes.wintypes
            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            SYNCHRONIZE = 0x0010
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid)
            if handle:
                exit_code = ctypes.c_ulong()
                is_active = False
                if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    is_active = (exit_code.value == 259)  # STILL_ACTIVE
                if is_active:
                    buf = ctypes.create_unicode_buffer(1024)
                    size = ctypes.wintypes.DWORD(len(buf))
                    if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                        exe_name = buf.value.lower()
                        kernel32.CloseHandle(handle)
                        return "python" in exe_name
                kernel32.CloseHandle(handle)
                return False
        except Exception:
            pass
        return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


scraper_process = None

@app.post("/api/run-scraper")
def run_scraper():
    global scraper_process
    if scraper_process and scraper_process.poll() is None:
        return {"status": "already_running"}
    
    lock_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", ".scraper.lock")
    if os.path.exists(lock_path):
        lock_pid = None
        try:
            with open(lock_path, "r", encoding="utf-8") as lf:
                lock_pid = int(lf.read().strip())
        except Exception:
            pass
        if lock_pid and is_process_running(lock_pid):
            return {"status": "already_running"}
        else:
            try:
                os.remove(lock_path)
            except OSError:
                pass

    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script_path = os.path.join(root_dir, "job_agent.py")
    python_exe = sys.executable
    candidate_job_agent = os.path.join(os.path.dirname(sys.executable), "job-agent.exe")
    system_job_agent = shutil.which("job-agent")
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    alt_job_agent = os.path.join(local_appdata, "Python", "pythoncore-3.14-64", "job-agent.exe") if local_appdata else ""
    if os.path.exists(candidate_job_agent):
        cmd = [candidate_job_agent]
    elif system_job_agent and os.path.exists(system_job_agent):
        cmd = [system_job_agent]
    elif alt_job_agent and os.path.exists(alt_job_agent):
        cmd = [alt_job_agent]
    else:
        cmd = [python_exe, script_path]
    
    creationflags = 0
    if os.name == 'nt':
        creationflags = 0x08000000
        
    scraper_process = subprocess.Popen(
        cmd,
        cwd=root_dir,
        creationflags=creationflags
    )
    return {"status": "started"}

@app.get("/api/scraper-status")
def scraper_status():
    from datetime import datetime
    import time
    global scraper_process
    is_running = False
    if scraper_process and scraper_process.poll() is None:
        is_running = True
    else:
        try:
            lock_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", ".scraper.lock")
            if os.path.exists(lock_path):
                lock_pid = None
                try:
                    with open(lock_path, "r", encoding="utf-8") as lf:
                        lock_pid = int(lf.read().strip())
                except Exception:
                    pass

                if lock_pid and is_process_running(lock_pid):
                    is_running = True
                elif lock_pid is None and (time.time() - os.path.getmtime(lock_path)) < 2700:
                    is_running = True
                else:
                    try:
                        os.remove(lock_path)
                    except OSError:
                        pass
        except Exception:
            pass
        
    last_run_str = "Unknown"
    try:
        eval_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "evaluation_brief.txt")
        if os.path.exists(eval_path):
            mtime = os.path.getmtime(eval_path)
            last_run_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %I:%M %p")
    except Exception:
        pass

    progress_data = None
    try:
        progress_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", ".scraper_progress.json")
        if os.path.exists(progress_path):
            with open(progress_path, "r", encoding="utf-8") as pf:
                progress_data = json.load(pf)
            if not is_running and progress_data:
                progress_data["is_running"] = False
    except Exception:
        pass

    return {"is_running": is_running, "last_run": last_run_str, "progress": progress_data}

@app.get("/api/pending-updates")
def get_pending_updates():
    alert_path = _get_alert_path()
    if not os.path.exists(alert_path):
        return {"proposals": []}
    try:
        with open(alert_path, 'r', encoding='utf-8') as f:
            content = json.load(f)

        proposals = []
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    if "field" in item and "type" in item:
                        proposals.append(item)
                    elif "updates" in item:
                        # Legacy convert
                        source = item.get("title", "AI Recommendation")
                        updates = item.get("updates", {})
                        for cat, val_list in updates.items():
                            for val in val_list:
                                proposals.append({
                                    "id": f"prop_leg_{uuid.uuid4().hex[:6]}",
                                    "source": source,
                                    "field": cat.upper(),
                                    "type": "add",
                                    "value": str(val).lower().strip(),
                                    "display_name": f"{cat.replace('_', ' ').title()}: {val}",
                                    "reason": "AI recommendation from job action"
                                })
        return {"proposals": proposals}
    except Exception as e:
        logging.error(f"Error fetching pending updates: {e}")
        return {"proposals": []}

class ProposalActionRequest(BaseModel):
    id: str = Field(default="")
    action: str = Field(description="'accept' or 'reject'")
    category: str = Field(default="")
    keyword: str = Field(default="")

@app.post("/api/pending-updates/action")
def resolve_pending_update(data: ProposalActionRequest, background_tasks: BackgroundTasks):
    alert_path = _get_alert_path()
    if not os.path.exists(alert_path):
        return {"status": "success"}
    
    try:
        with open(alert_path, 'r', encoding='utf-8') as f:
            content = json.load(f)

        proposals = content if isinstance(content, list) else []
        target_proposal = None
        remaining_proposals = []

        for p in proposals:
            match = False
            if data.id and p.get("id") == data.id:
                match = True
            elif data.category and data.keyword:
                val_str = str(p.get("value")).lower().strip()
                if p.get("field", "").lower() == data.category.lower() and val_str == data.keyword.lower().strip():
                    match = True

            if match:
                target_proposal = p
            else:
                remaining_proposals.append(p)

        if target_proposal and data.action == "accept":
            apply_config_updates([target_proposal])
            background_tasks.add_task(rescore_all_jobs)

        with open(alert_path, 'w', encoding='utf-8') as f:
            json.dump(remaining_proposals, f, indent=2, ensure_ascii=False)

        return {"status": "success", "accepted": data.action == "accept"}
    except Exception as e:
        logging.error(f"Error resolving pending update: {e}")
        return {"error": str(e), "status": "error"}

class BatchProposalActionRequest(BaseModel):
    action: str = Field(description="'accept_all' or 'reject_all'")

@app.post("/api/pending-updates/batch-action")
def batch_resolve_pending_updates(data: BatchProposalActionRequest, background_tasks: BackgroundTasks):
    alert_path = _get_alert_path()
    if not os.path.exists(alert_path):
        return {"status": "success"}
    
    try:
        with open(alert_path, 'r', encoding='utf-8') as f:
            content = json.load(f)

        proposals = content if isinstance(content, list) else []

        if data.action == "accept_all" and proposals:
            apply_config_updates(proposals)
            background_tasks.add_task(rescore_all_jobs)

        # Clear all pending proposals
        with open(alert_path, 'w', encoding='utf-8') as f:
            json.dump([], f, indent=2)

        return {"status": "success", "processed_count": len(proposals)}
    except Exception as e:
        logging.error(f"Error batch resolving proposals: {e}")
        return {"error": str(e), "status": "error"}

# ============================================
# Sub-routers: Profile, Co-Pilots, Auto-Pilot
# ============================================
from web.routers.profile import router as profile_router
from web.routers.copilots import router as copilots_router
from web.routers.autopilot import router as autopilot_router

app.include_router(profile_router)
app.include_router(copilots_router)
app.include_router(autopilot_router)



if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)

