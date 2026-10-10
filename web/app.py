from fastapi import FastAPI, BackgroundTasks, HTTPException, Request, UploadFile, File
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
import tempfile
import shutil
import uuid
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
from core.telegram_bot import (
    sync_queued_telegram_jobs, stop_bot_thread, is_bot_running, get_latest_chat_id_from_telegram,
    get_and_clear_new_telegram_jobs, get_bot_token, get_bot_info, resolve_chat_id_for_username,
    get_bot_url, get_bot_username
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

@app.on_event("shutdown")
def on_shutdown():
    try:
        stop_bot_thread()
    except Exception as e:
        logging.error(f"Error stopping Telegram Bot: {e}")

@app.get("/api/jobs")
def get_jobs(background_tasks: BackgroundTasks):
    """Returns all jobs so the frontend can filter them by status."""
    global _last_rescore_date
    today_str = datetime.now().strftime("%Y-%m-%d")
    if _last_rescore_date != today_str:
        background_tasks.add_task(rescore_all_jobs)
        _last_rescore_date = today_str
    jobs = get_jobs_by_status(['pending', 'liked', 'not_related'])
    return {"jobs": jobs}

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
        is_scholarship = req.is_scholarship or job_dict.get('job_type') == 'Scholarship'
        score = job_dict.get('relevance_score', 0)

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

class TelegramConfigRequest(BaseModel):
    username: str = Field(default="")

@app.get("/api/telegram/status")
def get_telegram_status():
    token = getattr(app_config, "TELEGRAM_BOT_TOKEN", None) or os.getenv("TELEGRAM_BOT_TOKEN", "") or get_bot_token()
    username = getattr(app_config, "TELEGRAM_USERNAME", None)
    if username is None:
        username = os.getenv("TELEGRAM_USERNAME", "")
    chat_id = getattr(app_config, "TELEGRAM_CHAT_ID", None)
    if chat_id is None:
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    bot_username = get_bot_username(token)
    bot_url = get_bot_url(token)
    return {
        "is_configured": bool(username or chat_id),
        "is_running": bool(username or chat_id),
        "username": username,
        "chat_id": chat_id,
        "has_chat_id": bool(chat_id),
        "bot_username": bot_username,
        "bot_url": bot_url
    }

@app.post("/api/telegram/detect-chat")
def detect_telegram_chat(req: TelegramConfigRequest):
    token = getattr(app_config, "TELEGRAM_BOT_TOKEN", None) or os.getenv("TELEGRAM_BOT_TOKEN", "") or get_bot_token()
    info = None
    for _ in range(4):
        info = get_latest_chat_id_from_telegram(token)
        if info and info.get("chat_id"):
            break
        time.sleep(0.5)

    if not info or not info.get("chat_id"):
        return {
            "status": "not_found",
            "message": "No recent message found yet. Please open the bot on Telegram and tap Start, then try again!"
        }
    return {
        "status": "success",
        "chat_id": info["chat_id"],
        "username": info.get("username", ""),
        "last_message": info.get("text", "")
    }

@app.post("/api/telegram/config")
def save_telegram_config(req: TelegramConfigRequest):
    new_username = req.username.strip().lstrip("@")
    token = getattr(app_config, "TELEGRAM_BOT_TOKEN", None) or os.getenv("TELEGRAM_BOT_TOKEN", "") or get_bot_token()

    current_username = getattr(app_config, "TELEGRAM_USERNAME", None)
    if current_username is None:
        current_username = os.getenv("TELEGRAM_USERNAME", "")
    current_username = (current_username or "").lstrip("@").strip()

    chat_id = getattr(app_config, "TELEGRAM_CHAT_ID", None)
    if chat_id is None:
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    chat_id = str(chat_id or "")

    if new_username:
        resolved = resolve_chat_id_for_username(token, new_username)
        if resolved:
            chat_id = resolved
        elif current_username.lower() != new_username.lower():
            chat_id = ""
    else:
        chat_id = ""

    env_path = ENV_FILE_PATH
    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    updated_user = False
    updated_chat = False
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("TELEGRAM_USERNAME"):
            new_lines.append(f'TELEGRAM_USERNAME="{new_username}"\n')
            updated_user = True
        elif stripped.startswith("TELEGRAM_CHAT_ID"):
            new_lines.append(f'TELEGRAM_CHAT_ID="{chat_id}"\n')
            updated_chat = True
        else:
            new_lines.append(line)

    if not updated_user:
        new_lines.append(f'TELEGRAM_USERNAME="{new_username}"\n')
    if not updated_chat:
        new_lines.append(f'TELEGRAM_CHAT_ID="{chat_id}"\n')

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    app_config.TELEGRAM_USERNAME = new_username
    app_config.TELEGRAM_CHAT_ID = chat_id
    os.environ["TELEGRAM_USERNAME"] = new_username
    os.environ["TELEGRAM_CHAT_ID"] = chat_id
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=env_path, override=True)
    except Exception:
        pass

    # Stop any old lingering threads if any
    stop_bot_thread()

    bot_username = get_bot_username(token)
    bot_url = get_bot_url(token)

    return {
        "status": "success",
        "username": new_username,
        "chat_id": chat_id,
        "bot_username": bot_username,
        "bot_url": bot_url,
        "message": f"Telegram username @{new_username} saved." if new_username else "Telegram username cleared."
    }

@app.get("/api/telegram/sync")
def sync_telegram_endpoint():
    """Triggered on app launch or GUI reload to sync queued jobs in one shot."""
    token = getattr(app_config, "TELEGRAM_BOT_TOKEN", None) or ""
    chat_id = getattr(app_config, "TELEGRAM_CHAT_ID", None) or ""
    if not token:
        return {"status": "not_configured", "count": 0, "jobs": [], "duplicates": 0}
    return sync_queued_telegram_jobs(token, chat_id)

@app.get("/api/telegram/check-new-jobs")
def check_new_telegram_jobs():
    """Alias for backwards compatibility with existing frontend calls."""
    token = getattr(app_config, "TELEGRAM_BOT_TOKEN", None) or ""
    chat_id = getattr(app_config, "TELEGRAM_CHAT_ID", None) or ""
    if not token:
        return {"count": 0, "jobs": [], "duplicates": 0}
    return sync_queued_telegram_jobs(token, chat_id)

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

    python_exe = sys.executable
    candidate_job_agent = os.path.join(os.path.dirname(sys.executable), "job-agent.exe")
    alt_job_agent = r"C:\Users\HP\AppData\Local\Python\pythoncore-3.14-64\job-agent.exe"
    if os.path.exists(candidate_job_agent):
        python_exe = candidate_job_agent
    elif os.path.exists(alt_job_agent):
        python_exe = alt_job_agent
    
    creationflags = 0
    if os.name == 'nt':
        creationflags = 0x08000000
        
    scraper_process = subprocess.Popen(
        [python_exe, script_path],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
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

from core.applicant_profile import load_profile, save_profile, scan_resume_directory
from core.database import backfill_job_classifications

@app.get("/api/profile")
def get_profile_endpoint():
    return load_profile()

@app.post("/api/profile")
def save_profile_endpoint(profile_data: Dict[str, Any]):
    success = save_profile(profile_data)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to save profile data.")
    return {"status": "success", "profile": load_profile()}

@app.api_route("/api/profile/scan-resumes", methods=["GET", "POST"])
def scan_resumes_endpoint(base_dir: Optional[str] = None):
    return scan_resume_directory(base_dir)

@app.post("/api/upload-role-resume")
async def upload_role_resume_endpoint(file: UploadFile = File(...)):
    """Uploads a role resume PDF/DOCX to data/resumes and returns its saved absolute path."""
    try:
        resumes_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "resumes")
        os.makedirs(resumes_dir, exist_ok=True)
        safe_filename = os.path.basename(file.filename)
        dest_path = os.path.join(resumes_dir, safe_filename)
        with open(dest_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        abs_path = os.path.abspath(dest_path)
        return {
            "status": "success",
            "filename": safe_filename,
            "file_path": abs_path,
            "size_kb": round(os.path.getsize(dest_path) / 1024, 1)
        }
    except Exception as e:
        logging.error(f"Error uploading role resume: {e}")
        return {"status": "error", "error": str(e)}

@app.post("/api/check-resume-file")
async def check_resume_file_endpoint(req: Dict[str, Any]):
    """Checks whether a given resume file path exists on disk and returns its metadata."""
    path = (req.get("path") or "").strip()
    if not path:
        return {"exists": False, "filename": "", "size_kb": 0}
    
    if not os.path.isabs(path):
        resolved = os.path.join(os.path.dirname(os.path.dirname(__file__)), path)
    else:
        resolved = path
        
    exists = os.path.exists(resolved) and os.path.isfile(resolved)
    size_kb = round(os.path.getsize(resolved) / 1024, 1) if exists else 0
    return {
        "exists": exists,
        "path": os.path.abspath(resolved) if exists else path,
        "filename": os.path.basename(resolved),
        "size_kb": size_kb
    }

@app.get("/api/auto-apply/settings")
def get_auto_apply_settings_endpoint():
    profile = load_profile()
    return profile.get("auto_apply_settings", {})

@app.post("/api/auto-apply/settings")
def save_auto_apply_settings_endpoint(settings_data: Dict[str, Any]):
    profile = load_profile()
    profile["auto_apply_settings"] = settings_data
    save_profile(profile)
    return {"status": "success", "settings": profile.get("auto_apply_settings", {})}

@app.post("/api/jobs/classify-all")
def classify_all_jobs_endpoint():
    count = backfill_job_classifications()
    return {"status": "success", "classified_count": count}

# ==========================================
# Email Co-Pilot & Email Launchers Endpoints
# ==========================================
from appliers.email_generator import generate_email_draft
from appliers.gmail_launcher import prepare_gmail_launch, copy_file_to_clipboard, reveal_in_explorer
from appliers.outlook_launcher import launch_outlook_compose
from core.database import DB_PATH
import sqlite3

class EmailDraftRequest(BaseModel):
    job_id: str

class OpenInGmailRequest(BaseModel):
    job_id: Optional[str] = None
    recipient: str = Field(default="")
    subject: str = Field(default="")
    body: str = Field(default="")
    cv_path: Optional[str] = None
    open_browser: bool = Field(default=False)

class OpenInOutlookRequest(BaseModel):
    job_id: Optional[str] = None
    recipient: str = Field(default="")
    subject: str = Field(default="")
    body: str = Field(default="")
    raw_body: Optional[str] = None
    cv_path: Optional[str] = None
    personal_signature: Optional[str] = None

class MarkAppliedRequest(BaseModel):
    job_id: str
    recipient: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    applied_via: Optional[str] = "outlook_copilot"

@app.post("/api/email/generate-draft")
def generate_email_draft_endpoint(req: EmailDraftRequest):
    draft = generate_email_draft(job_id=req.job_id)
    if draft.get("status") == "error":
        raise HTTPException(status_code=404, detail=draft.get("message", "Job not found"))
    return draft

@app.post("/api/email/open-in-outlook")
def open_in_outlook_endpoint(req: OpenInOutlookRequest):
    res = launch_outlook_compose(
        recipient=req.recipient,
        subject=req.subject,
        body=req.body,
        cv_path=req.cv_path,
        raw_body=req.raw_body,
        personal_signature=req.personal_signature
    )
    if res.get("status") == "error":
        raise HTTPException(status_code=500, detail=res.get("message", "Failed to launch Outlook"))
    return res

@app.post("/api/email/open-in-gmail")
def open_in_gmail_endpoint(req: OpenInGmailRequest):
    res = prepare_gmail_launch(
        recipient=req.recipient,
        subject=req.subject,
        body=req.body,
        cv_path=req.cv_path,
        open_browser=req.open_browser
    )
    return res

@app.post("/api/email/copy-cv")
def copy_cv_endpoint(req: Dict[str, Any]):
    cv_path = req.get("cv_path")
    if not cv_path or not os.path.exists(cv_path):
        raise HTTPException(status_code=404, detail="CV file not found")
    copied = copy_file_to_clipboard(cv_path)
    return {"status": "success", "copied": copied, "cv_path": cv_path}

@app.post("/api/email/reveal-cv")
def reveal_cv_endpoint(req: Dict[str, Any]):
    cv_path = req.get("cv_path")
    if not cv_path or not os.path.exists(cv_path):
        raise HTTPException(status_code=404, detail="CV file not found")
    revealed = reveal_in_explorer(cv_path)
    return {"status": "success", "revealed": revealed}

@app.post("/api/email/mark-applied")
def mark_email_applied_endpoint(req: MarkAppliedRequest):
    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=500, detail="Database not found")
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        cursor = conn.cursor()
        now_str = datetime.now().isoformat()
        
        cursor.execute("SELECT apply_payload FROM jobs WHERE job_id = ?", (req.job_id,))
        row = cursor.fetchone()
        payload = {}
        if row and row[0]:
            try:
                payload = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            except Exception:
                payload = {}
                
        payload["sent_email"] = {
            "recipient": req.recipient,
            "subject": req.subject,
            "body": req.body,
            "applied_via": req.applied_via or "outlook_copilot",
            "timestamp": now_str
        }
        
        cursor.execute("""
            UPDATE jobs 
            SET is_applied = 1, apply_status = 'applied', applied_at = ?, apply_payload = ?
            WHERE job_id = ?
        """, (now_str, json.dumps(payload, ensure_ascii=False), req.job_id))
        conn.commit()
        conn.close()
        return {"status": "success", "job_id": req.job_id, "applied_at": now_str}
    except Exception as e:
        logging.error(f"Error marking job as applied: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================
# WhatsApp Co-Pilot & Desktop Launch Endpoints
# ============================================
from appliers.whatsapp_copilot import generate_whatsapp_pitch
from appliers.whatsapp_launcher import launch_whatsapp_desktop, launch_whatsapp_web

class WhatsAppPitchRequest(BaseModel):
    job_id: str

class OpenInWhatsAppDesktopRequest(BaseModel):
    phone: str = Field(default="")
    pitch: str = Field(default="")
    cv_path: Optional[str] = None
    auto_attach: Optional[bool] = True

class MarkWhatsAppAppliedRequest(BaseModel):
    job_id: str
    phone: Optional[str] = None
    pitch: Optional[str] = None
    applied_via: Optional[str] = "whatsapp_desktop"

@app.post("/api/whatsapp/generate-pitch")
def generate_whatsapp_pitch_endpoint(req: WhatsAppPitchRequest):
    pitch_data = generate_whatsapp_pitch(job_id=req.job_id)
    if pitch_data.get("status") == "error":
        raise HTTPException(status_code=404, detail=pitch_data.get("message", "Job not found"))
    return pitch_data

@app.post("/api/whatsapp/open-in-desktop")
def open_in_whatsapp_desktop_endpoint(req: OpenInWhatsAppDesktopRequest):
    res = launch_whatsapp_desktop(
        phone=req.phone,
        pitch=req.pitch,
        cv_path=req.cv_path,
        auto_attach=req.auto_attach if req.auto_attach is not None else True
    )
    if res.get("status") == "error":
        raise HTTPException(status_code=500, detail=res.get("message", "Failed to launch WhatsApp Desktop"))
    return res

@app.post("/api/whatsapp/copy-cv")
def copy_whatsapp_cv_endpoint(req: Dict[str, Any]):
    cv_path = req.get("cv_path")
    if not cv_path or not os.path.exists(cv_path):
        raise HTTPException(status_code=404, detail="CV file not found")
    copied = copy_file_to_clipboard(cv_path)
    return {"status": "success", "copied": copied, "cv_path": cv_path}

@app.post("/api/whatsapp/reveal-cv")
def reveal_whatsapp_cv_endpoint(req: Dict[str, Any]):
    cv_path = req.get("cv_path")
    if not cv_path or not os.path.exists(cv_path):
        raise HTTPException(status_code=404, detail="CV file not found")
    revealed = reveal_in_explorer(cv_path)
    return {"status": "success", "revealed": revealed}

@app.post("/api/whatsapp/mark-applied")
def mark_whatsapp_applied_endpoint(req: MarkWhatsAppAppliedRequest):
    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=500, detail="Database not found")
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        cursor = conn.cursor()
        now_str = datetime.now().isoformat()
        
        cursor.execute("SELECT apply_payload FROM jobs WHERE job_id = ?", (req.job_id,))
        row = cursor.fetchone()
        payload = {}
        if row and row[0]:
            try:
                payload = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            except Exception:
                payload = {}
                
        payload["sent_whatsapp"] = {
            "phone": req.phone,
            "pitch": req.pitch,
            "applied_via": req.applied_via or "whatsapp_desktop",
            "timestamp": now_str
        }
        
        cursor.execute("""
            UPDATE jobs 
            SET is_applied = 1, apply_status = 'applied', applied_at = ?, apply_payload = ?
            WHERE job_id = ?
        """, (now_str, json.dumps(payload, ensure_ascii=False), req.job_id))
        conn.commit()
        conn.close()
        return {"status": "success", "job_id": req.job_id, "applied_at": now_str}
    except Exception as e:
        logging.error(f"Error marking WhatsApp job as applied: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================
# Easy Apply Co-Pilot & Assisted Session Endpoints
# ============================================
from appliers.easy_apply_copilot import prepare_easy_apply, launch_easy_apply_session, get_session

class EasyApplyPrepareRequest(BaseModel):
    job_id: str

class EasyApplyLaunchRequest(BaseModel):
    job_id: str
    headed: Optional[bool] = True

class MarkEasyApplyAppliedRequest(BaseModel):
    job_id: str
    applied_via: Optional[str] = "easy_apply_copilot"

@app.post("/api/easy-apply/prepare")
def easy_apply_prepare_endpoint(req: EasyApplyPrepareRequest):
    data = prepare_easy_apply(job_id=req.job_id)
    if data.get("status") == "error":
        raise HTTPException(status_code=404, detail=data.get("message", "Job not found"))
    return data

@app.post("/api/easy-apply/launch-session")
def easy_apply_launch_session_endpoint(req: EasyApplyLaunchRequest):
    res = launch_easy_apply_session(job_id=req.job_id, headed=req.headed if req.headed is not None else True)
    if res.get("status") == "error":
        raise HTTPException(status_code=500, detail=res.get("message", "Failed to launch Easy Apply session"))
    return res

@app.get("/api/easy-apply/status/{job_id}")
def easy_apply_status_endpoint(job_id: str):
    session = get_session(job_id)
    if not session:
        return {"status": "idle", "job_id": job_id, "current_step": "Not started", "logs": []}
    return session.to_dict()

@app.post("/api/easy-apply/mark-applied")
def mark_easy_apply_applied_endpoint(req: MarkEasyApplyAppliedRequest):
    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=500, detail="Database not found")
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        cursor = conn.cursor()
        now_str = datetime.now().isoformat()
        
        cursor.execute("SELECT apply_payload FROM jobs WHERE job_id = ?", (req.job_id,))
        row = cursor.fetchone()
        payload = {}
        if row and row[0]:
            try:
                payload = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            except Exception:
                payload = {}
                
        payload["sent_easy_apply"] = {
            "applied_via": req.applied_via or "easy_apply_copilot",
            "timestamp": now_str
        }
        
        cursor.execute("""
            UPDATE jobs 
            SET is_applied = 1, apply_status = 'applied', applied_at = ?, apply_payload = ?
            WHERE job_id = ?
        """, (now_str, json.dumps(payload, ensure_ascii=False), req.job_id))
        conn.commit()
        conn.close()
        return {"status": "success", "job_id": req.job_id, "applied_at": now_str}
    except Exception as e:
        logging.error(f"Error marking Easy Apply job as applied: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ----------------------------------------------------
# Company ATS & Web Forms Co-Pilot Endpoints (Batch 5)
# ----------------------------------------------------
from appliers.ats_copilot import (
    prepare_ats_application,
    launch_ats_session,
    get_ats_session,
    generate_ats_cover_letter,
    mark_ats_applied
)

class AtsPrepareRequest(BaseModel):
    job_id: str

class AtsLaunchRequest(BaseModel):
    job_id: str
    headed: Optional[bool] = True

class AtsCoverLetterRequest(BaseModel):
    job_id: str

class MarkAtsAppliedRequest(BaseModel):
    job_id: str
    applied_via: Optional[str] = "ats_copilot"

@app.post("/api/ats/prepare")
def ats_prepare_endpoint(req: AtsPrepareRequest):
    data = prepare_ats_application(job_id=req.job_id)
    if data.get("status") == "error":
        raise HTTPException(status_code=404, detail=data.get("message", "Job not found"))
    return data

@app.post("/api/ats/launch-session")
def ats_launch_session_endpoint(req: AtsLaunchRequest):
    res = launch_ats_session(job_id=req.job_id, headed=req.headed if req.headed is not None else True)
    if res.get("status") == "error":
        raise HTTPException(status_code=500, detail=res.get("message", "Failed to launch ATS session"))
    return res

@app.get("/api/ats/status/{job_id}")
def ats_status_endpoint(job_id: str):
    session = get_ats_session(job_id)
    if not session:
        return {"status": "idle", "job_id": job_id, "current_step": "Not started", "logs": []}
    return session.to_dict()

@app.post("/api/ats/generate-cover-letter")
def ats_cover_letter_endpoint(req: AtsCoverLetterRequest):
    from core.applicant_profile import get_resume_for_role
    from core.cv_parser import extract_text_from_file

    job = get_job_by_id(req.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    cv_path = get_resume_for_role(job.get("title", ""))
    cv_text = ""
    if cv_path and os.path.exists(cv_path):
        try:
            cv_text = extract_text_from_file(cv_path)
        except Exception:
            pass
    cl = generate_ats_cover_letter(
        job_title=job.get("title", ""),
        company=job.get("company", ""),
        location=job.get("location", ""),
        job_description=job.get("description", ""),
        cv_text=cv_text
    )
    return {"status": "success", "job_id": req.job_id, "cover_letter": cl}

@app.post("/api/ats/mark-applied")
def mark_ats_applied_endpoint(req: MarkAtsAppliedRequest):
    res = mark_ats_applied(job_id=req.job_id)
    if res.get("status") == "error":
        raise HTTPException(status_code=500, detail=res.get("message", "Failed to mark ATS job as applied"))
    return res


# ----------------------------------------------------
# Auto-Pilot & Applications History Endpoints (Phase 2)
# ----------------------------------------------------
from appliers.email_worker import (
    get_autopilot_state,
    run_email_autopilot_batch
)
from appliers.whatsapp_worker import run_whatsapp_autopilot_batch
from appliers.master_orchestrator import (
    run_master_autopilot_cycle,
    is_cycle_active,
    get_applications_history,
    get_applications_aggregate_stats,
    resolve_telegram_hitl_answer
)

class RunCycleRequest(BaseModel):
    force: Optional[bool] = False
    dry_run: Optional[bool] = False

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

@app.post("/api/autopilot/run-cycle")
def autopilot_run_cycle_endpoint(req: RunCycleRequest, bg_tasks: BackgroundTasks):
    if is_cycle_active():
        return {"status": "already_running", "message": "Auto-Pilot cycle is currently executing in background."}
    bg_tasks.add_task(run_master_autopilot_cycle, force=req.force or False, dry_run=req.dry_run or False)
    return {"status": "started", "message": "Master Auto-Pilot cycle dispatched to background."}

class ToggleAutoPilotRequest(BaseModel):
    enabled: bool

@app.get("/api/autopilot/status")
def autopilot_status_endpoint():
    state = get_autopilot_state()
    state["is_cycle_running"] = is_cycle_active()
    profile = load_profile()
    settings = profile.get("auto_apply_settings", {})
    is_enabled = bool(settings.get("enabled", False))
    state["is_enabled"] = is_enabled
    state["is_paused"] = not is_enabled
    return state

@app.post("/api/autopilot/toggle-state")
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

@app.post("/api/autopilot/run-email-batch")
def autopilot_run_email_batch_endpoint(req: RunEmailBatchRequest):
    res = run_email_autopilot_batch(force=req.force or False, dry_run=req.dry_run or False, batch_limit=req.batch_limit)
    return res

@app.post("/api/autopilot/run-whatsapp-batch")
def autopilot_run_whatsapp_batch_endpoint(req: RunWhatsappBatchRequest):
    res = run_whatsapp_autopilot_batch(force=req.force or False, dry_run=req.dry_run or False, batch_limit=req.batch_limit)
    return res

@app.get("/api/applications/history")
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

@app.get("/api/applications/stats")
def applications_stats_endpoint():
    return get_applications_aggregate_stats()

@app.post("/api/applications/retry")
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

@app.post("/api/autopilot/hitl-answer")
def autopilot_hitl_answer_endpoint(req: HitlAnswerRequest):
    success = resolve_telegram_hitl_answer(job_id=req.job_id, question=req.question, answer=req.answer)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to save HITL answer")
    return {"status": "success", "message": "Answer saved and application resumed."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)

