from fastapi import FastAPI, BackgroundTasks, HTTPException, Request, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
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

from core.database import get_jobs_by_status, update_job_status, get_job_by_id, toggle_job_applied
from core.config_tuner import analyze_job_and_tune_config
from core.cv_parser import parse_cv_with_ai
from core.scorer import rescore_all_jobs

app = FastAPI(title="Job Dashboard")

# Mount static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
def read_root():
    return FileResponse(os.path.join(static_dir, "index.html"))

@app.get("/api/jobs")
def get_jobs():
    """Returns all jobs so the frontend can filter them by status."""
    jobs = get_jobs_by_status(['pending', 'liked', 'not_related'])
    return {"jobs": jobs}

@app.get("/api/config")
def get_config():
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'core', 'config.json')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/config")
async def update_config(request: Request):
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'core', 'config.json')
    try:
        new_config = await request.json()
        new_config["last_reviewed_date"] = datetime.now().strftime("%Y-%m-%d")
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(new_config, f, indent=2, ensure_ascii=False)
        return {"status": "success", "last_reviewed_date": new_config["last_reviewed_date"]}
    except Exception as e:
        logging.error(f"Error updating config: {e}")
        return {"error": "Failed to update config"}

@app.post("/api/rerank-jobs")
def rerank_jobs_endpoint():
    try:
        result = rescore_all_jobs()
        return result
    except Exception as e:
        logging.error(f"Rescore failed: {e}")
        return {"error": "Rescore failed", "status": "error"}

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


scraper_process = None

@app.post("/api/run-scraper")
def run_scraper():
    global scraper_process
    if scraper_process and scraper_process.poll() is None:
        return {"status": "already_running"}
    
    script_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "job_agent.py")
    python_exe = sys.executable
    
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
                if (time.time() - os.path.getmtime(lock_path)) < 2700:
                    is_running = True
                else:
                    os.remove(lock_path)
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

    return {"is_running": is_running, "last_run": last_run_str}

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
def resolve_pending_update(data: ProposalActionRequest):
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

        with open(alert_path, 'w', encoding='utf-8') as f:
            json.dump(remaining_proposals, f, indent=2, ensure_ascii=False)

        return {"status": "success", "accepted": data.action == "accept"}
    except Exception as e:
        logging.error(f"Error resolving pending update: {e}")
        return {"error": str(e), "status": "error"}

class BatchProposalActionRequest(BaseModel):
    action: str = Field(description="'accept_all' or 'reject_all'")

@app.post("/api/pending-updates/batch-action")
def batch_resolve_pending_updates(data: BatchProposalActionRequest):
    alert_path = _get_alert_path()
    if not os.path.exists(alert_path):
        return {"status": "success"}
    
    try:
        with open(alert_path, 'r', encoding='utf-8') as f:
            content = json.load(f)

        proposals = content if isinstance(content, list) else []

        if data.action == "accept_all" and proposals:
            apply_config_updates(proposals)

        # Clear all pending proposals
        with open(alert_path, 'w', encoding='utf-8') as f:
            json.dump([], f, indent=2)

        return {"status": "success", "processed_count": len(proposals)}
    except Exception as e:
        logging.error(f"Error batch resolving proposals: {e}")
        return {"error": str(e), "status": "error"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)

